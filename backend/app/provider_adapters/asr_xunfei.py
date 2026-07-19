"""Xunfei ASR provider adapter (BE-025).

This is the ASR twin of the BE-019 provider abstraction. It reads a resolved
``ResolvedProvider`` (``provider_type == ASR``) and exposes a single
``transcribe(audio_bytes, mime) -> ASRResult`` entry point.

Two modes are supported (see ``provider_adapters.__init__``):

- **Mock mode** (default) — when no enabled ASR ``provider_configs`` row exists
  for the tenant, or when ``PYMENTOR_ASR_MOCK=1`` is set. Returns a
  deterministic stub transcription so the voice-question notebook flow works
  without a live dependency. This is the only mode exercised by unit tests.
- **Live mode** — when a real credential is authorized. The adapter posts to
  the Xunfei ASR endpoint; transport/upstream failures surface as
  ``ProviderAdapterError``. Live verification is tracked as INT-010 NOT-RUN.

Shape is identical to BE-022 (TTS) and BE-024 (OCR): a module per vendor, a
single ``transcribe`` entry point, shared typed errors, the shared
``mock_mode_enabled`` helper, and a ``build_asr_adapter`` factory the API layer
imports from the package root.

Redaction: the adapter holds the raw audio only for the duration of the call;
it is never persisted by this layer (the caller decides audit detail).
"""

from __future__ import annotations

from app.contracts.asr import ASRResult
from app.provider_adapters import (
    ProviderAdapterError,
    mock_mode_enabled,
)
from app.providers import ResolvedProvider

_MOCK_FLAG = "PYMENTOR_ASR_MOCK"

# Deterministic stub output for mock mode. A plausible short student question
# in Mandarin (the primary locale); tests assert on these constants. Live mode
# would return the vendor's actual transcript instead.
MOCK_ASR_TRANSCRIPT = "请解释一下 Python 的 for 循环是怎么工作的。"
MOCK_ASR_LANGUAGE = "zh-CN"
MOCK_ASR_CONFIDENCE = 0.97

# Stub duration (ms). Real audio decoding is out of scope for mock mode (no
# decoder dependency); the stub returns a small fixed duration so the response
# contract stays populated and tests stay deterministic. It is well within the
# endpoint's 60s limit.
_MOCK_DURATION_MS = 4_200


def _mock_transcription(audio_bytes: bytes) -> ASRResult:
    """Deterministic stub transcription for mock mode.

    ``audio_bytes`` must be non-empty (the endpoint rejects empty uploads at the
    boundary; this guard keeps the adapter safe to call directly in unit
    tests). The stub never inspects the audio content — it returns the fixed
    :data:`MOCK_ASR_TRANSCRIPT` so tests are deterministic.
    """

    if not audio_bytes:
        raise ValueError("empty audio payload")
    return ASRResult(
        transcript=MOCK_ASR_TRANSCRIPT,
        duration_ms=_MOCK_DURATION_MS,
        confidence=MOCK_ASR_CONFIDENCE,
        language=MOCK_ASR_LANGUAGE,
        provider_mode="MOCK",
    )


class XunfeiAsrAdapter:
    """Adapter for the Xunfei (iFlytek) ASR provider.

    Stateless: a fresh instance is built per request from the
    ``ResolvedProvider`` so a credential rotation always picks up the latest
    key (mirrors BE-019's no-process-cache contract).
    """

    def __init__(self, provider: ResolvedProvider | None) -> None:
        self._provider = provider

    @property
    def is_mock(self) -> bool:
        """True when the adapter returns mock transcriptions."""

        return mock_mode_enabled(flag_name=_MOCK_FLAG, provider=self._provider)

    def transcribe(self, audio_bytes: bytes, mime: str) -> ASRResult:
        """Transcribe ``audio_bytes`` (declared ``mime``) to ``ASRResult``.

        ``mime`` is the upload's MIME type (echoed into audit logs only); the
        adapter does not decode it. Raises ``ProviderAdapterError`` when a live
        transcription is requested but the upstream fails.
        """

        if self.is_mock:
            return _mock_transcription(audio_bytes)

        # Live path (exercised only by INT-010 against the real upstream).
        assert self._provider is not None  # invariant: live ⇒ provider set
        try:
            return self._transcribe_live(audio_bytes, mime)
        except ProviderAdapterError:
            raise
        except Exception as error:  # pragma: no cover - live path only
            raise ProviderAdapterError("Xunfei ASR request failed") from error

    def _transcribe_live(
        self, audio_bytes: bytes, mime: str
    ) -> ASRResult:  # pragma: no cover - live path
        """Live Xunfei ASR call.

        Gated behind ``is_mock is False`` and only exercised by INT-010. The
        implementation will sign and post per Xunfei's WebAPI when a live
        credential is available; for now it fails closed instead of returning
        fake text, so a misconfigured live path is never silently degraded.
        """

        del audio_bytes, mime
        raise ProviderAdapterError("Xunfei ASR live mode is not configured")


def build_asr_adapter(provider: ResolvedProvider | None) -> XunfeiAsrAdapter:
    """Factory used by the API layer; tests override this for fakes."""

    return XunfeiAsrAdapter(provider)


__all__ = [
    "MOCK_ASR_CONFIDENCE",
    "MOCK_ASR_LANGUAGE",
    "MOCK_ASR_TRANSCRIPT",
    "XunfeiAsrAdapter",
    "build_asr_adapter",
]
