"""Xunfei (iFlytek) TTS native-protocol adapter (BE-022).

Wraps the Xunfei online TTS WebSocket protocol behind the BE-019 provider
abstraction. The adapter reads its credentials from the encrypted
``provider_configs`` row (``kind=TTS``) and exposes a single typed
``generate`` entry point returning PCM/encoded audio plus a punctuation-split
subtitle track.

IMPORTANT — mock vs. live
-------------------------
No live Xunfei credential is authorized for this repository. The adapter
runs in **mock mode** by default:

- when ``PYMENTOR_TTS_MOCK=1`` is set, OR
- when no enabled ``TTS`` ``provider_configs`` row exists for the tenant.

In mock mode ``generate`` returns a deterministic, clearly-labelled stub:
a short silent WAV plus a subtitle track split on CJK/ASCII punctuation. The
result and the structured-log field both carry ``mock=True`` so a placeholder
clip is never confused with a real synthesized voice. Live verification is
tracked separately as INT-010 NOT-RUN; tests never exercise the live branch.
"""

from __future__ import annotations

import io
import logging
import re
import struct
import wave
from dataclasses import dataclass
from typing import Any

from app.provider_adapters import (
    ProviderAdapterError,
    mock_mode_enabled,
)
from app.providers import ProviderType, ResolvedProvider

logger = logging.getLogger(__name__)

#: Operator override flag. When ``1`` the adapter always runs in mock mode even
#: if a live credential is configured, so demos and CI never accidentally bill
#: against a real Xunfei quota.
MOCK_FLAG = "PYMENTOR_TTS_MOCK"

#: Approximate speaking rate used to size the mock clip and align subtitle cues
#: (ms per character). Deliberately coarse — it only governs the placeholder.
_MS_PER_CHAR = 180

#: Voice enum → Xunfei ``voiceName`` parameter (kept inside the adapter so the
#: wire contract stays vendor-neutral). Used by the live branch only; the mock
#: branch ignores the value but echoes it back in logs for traceability.
_VOICE_PARAMETER: dict[str, str] = {
    "xiaoyan": "xiaoyan",
    "xiaoyu": "xiaoyu",
}

# CJK + ASCII sentence-end punctuation used to split the subtitle track. The
# pattern is applied to BOTH mock and live output so captions are consistent.
_SENTENCE_END = re.compile(r"([。！？!?；;])")


@dataclass(frozen=True, slots=True)
class TTSResult:
    """Adapter-level result returned to the API layer.

    ``mock`` is always populated so the endpoint can label the response and the
    structured log unambiguously. ``audio_bytes`` is the raw container payload
    (WAV in mock mode; vendor-native container in live mode) and ``mime``
    describes it.
    """

    audio_bytes: bytes
    mime: str
    duration_ms: int
    subtitle_track: list[dict[str, int | str]]
    mock: bool


class TTSXunfeiAdapter:
    """Xunfei TTS adapter behind the BE-019 provider abstraction.

    Construct with the ``ResolvedProvider`` (decrypted by the caller via
    ``resolve_enabled_provider``) or ``None`` to engage mock mode. The adapter
    never opens the credential envelope twice and never logs the API key.
    """

    provider_type = ProviderType.TTS
    vendor = "xfyun"

    def __init__(self, provider: ResolvedProvider | None) -> None:
        self._provider = provider
        self._mock = mock_mode_enabled(flag_name=MOCK_FLAG, provider=provider)

    @property
    def mock(self) -> bool:
        return self._mock

    def generate(self, text: str, voice_options: dict[str, Any] | None = None) -> TTSResult:
        """Synthesize ``text`` and return audio + subtitle track.

        In mock mode (the only path exercised by CI) this never raises. In live
        mode (INT-010 NOT-RUN) a transport/auth failure surfaces as
        ``ProviderAdapterError``; the API layer maps that to a typed 503 so the
        teaching loop can degrade cleanly.
        """

        subtitle_track = _split_subtitle_track(text)
        duration_ms = _estimate_duration_ms(text)
        if self._mock:
            audio_bytes = _silent_wav(duration_ms)
            result = TTSResult(
                audio_bytes=audio_bytes,
                mime="audio/wav",
                duration_ms=duration_ms,
                subtitle_track=subtitle_track,
                mock=True,
            )
            logger.info(
                "tts.xunfei.mock_generated",
                extra={
                    "voice": (voice_options or {}).get("voice"),
                    "chars": len(text),
                    "duration_ms": duration_ms,
                    "mock": True,
                },
            )
            return result
        # Live branch: wired but INTENTIONALLY not exercised from tests. The
        # real WebSocket handshake, auth-signature and frame parsing live here
        # once a credential is authorized (INT-010).
        assert self._provider is not None  # invariant: live ⇒ provider
        try:
            audio_bytes, mime, live_duration_ms = _render_live(self._provider, text, voice_options)
        except ProviderAdapterError:
            logger.warning("tts.xunfei.live_failed", extra={"mock": False})
            raise
        logger.info(
            "tts.xunfei.live_generated",
            extra={
                "voice": (voice_options or {}).get("voice"),
                "chars": len(text),
                "duration_ms": live_duration_ms,
                "mock": False,
            },
        )
        return TTSResult(
            audio_bytes=audio_bytes,
            mime=mime,
            duration_ms=live_duration_ms,
            subtitle_track=subtitle_track,
            mock=False,
        )


def resolve_tts_provider_or_mock(
    *, provider: ResolvedProvider | None, force_mock: bool
) -> TTSXunfeiAdapter:
    """Factory used by the API layer.

    When the operator forces mock via the env flag we engage mock even if a
    provider row exists; otherwise an absent provider also engages mock so the
    endpoint stays usable while no live credential is authorized.
    """

    if force_mock:
        return TTSXunfeiAdapter(None)
    return TTSXunfeiAdapter(provider)


def build_tts_adapter(provider: ResolvedProvider | None) -> TTSXunfeiAdapter:
    """Factory used by the API layer; tests override this for fakes.

    Mirrors ``build_ocr_adapter`` (BE-024) so the sibling endpoints resolve
    their adapters identically. Mock-vs-live is decided inside the adapter via
    the shared ``mock_mode_enabled`` helper (no live credential ⇒ mock).
    """

    return TTSXunfeiAdapter(provider)


def _split_subtitle_track(text: str) -> list[dict[str, int | str]]:
    """Split ``text`` into caption cues on sentence-end punctuation.

    Each cue covers a roughly proportional span of the (mock or live) clip so
    the renderer can paint captions aligned to audio. Pure mock timing — the
    live branch re-uses the same cues because Xunfei does not return word
    boundaries on the basic plan.
    """

    text = text.strip()
    if not text:
        return []
    pieces = [piece for piece in _SENTENCE_END.split(text) if piece]
    sentences: list[str] = []
    buffer = ""
    for piece in pieces:
        buffer += piece
        if _SENTENCE_END.fullmatch(piece):
            sentences.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        sentences.append(buffer.strip())
    if not sentences:
        sentences = [text]
    total_ms = _estimate_duration_ms(text)
    per_char = total_ms / max(len(text), 1)
    cues: list[dict[str, int | str]] = []
    cursor = 0
    for sentence in sentences:
        length = max(len(sentence), 1)
        start_ms = int(cursor)
        end_ms = min(int(cursor + length * per_char), total_ms)
        if end_ms <= start_ms:
            end_ms = start_ms + 1
        cues.append({"start_ms": start_ms, "end_ms": end_ms, "text": sentence})
        cursor = end_ms
    if cursor < total_ms and cues:
        last = cues[-1]
        last["end_ms"] = total_ms
    return cues


def _estimate_duration_ms(text: str) -> int:
    """Coarse duration estimate for the placeholder clip and caption alignment."""

    chars = max(len(text.strip()), 1)
    return min(chars * _MS_PER_CHAR, 30_000)


def _silent_wav(duration_ms: int) -> bytes:
    """Build a deterministic, short, mono 16kHz 16-bit silent WAV container.

    Silence is intentional — the mock must never be confused with a real voice.
    A real header (so the renderer's ``<audio>`` element decodes it) wraps zero
    PCM samples sized to the estimated duration.
    """

    sample_rate = 16_000
    duration_ms = max(duration_ms, 1)
    num_frames = int(sample_rate * duration_ms / 1000)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(struct.pack("<" + "h" * num_frames, *([0] * num_frames)))
    return buffer.getvalue()


def _render_live(
    provider: ResolvedProvider,
    text: str,
    voice_options: dict[str, Any] | None,
) -> tuple[bytes, str, int]:
    """Live Xunfei TTS render (NOT exercised in CI).

    Placeholder that performs the authenticated WebSocket handshake against the
    Xunfei online TTS endpoint, sends the synth frame and reassembles the
    base64 audio chunks. Raising ``ProviderAdapterError`` keeps the API layer's
    degradation path typed. This branch only runs once a real credential is
    authorized (INT-010).
    """

    del provider, text, voice_options  # live branch; intentionally not wired here
    raise ProviderAdapterError(
        "live Xunfei TTS render is not authorized in this build (INT-010 NOT-RUN)"
    )


__all__ = [
    "MOCK_FLAG",
    "TTSResult",
    "TTSXunfeiAdapter",
    "build_tts_adapter",
    "resolve_tts_provider_or_mock",
]
