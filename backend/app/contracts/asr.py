"""Strict contracts for student-facing ASR (BE-025).

A student records a voice question and receives the transcribed text, which
feeds directly into the BE-007 Q&A flow. No raw audio is persisted: the upload
is transcribed in-memory through the Xunfei ASR adapter (BE-019 resolved
provider, kind=ASR) and purged; only audit/observability metadata (size, mime,
duration, provider outcome) is recorded. Shape parity with BE-022 (TTS) and
BE-024 (OCR).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# MIME types accepted for ASR uploads. The allowlist covers the containers
# browsers commonly emit for ``MediaRecorder`` (wav/webm/ogg) plus a widely
# supported fallback (mp3). It is applied at the boundary along with hard size
# and duration caps so a hostile or accidental payload never reaches the
# provider. ``audio/x-wav`` / ``audio/wave`` are accepted because some browsers
# report WAV uploads with those variants.
ASR_ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {"audio/wav", "audio/x-wav", "audio/wave", "audio/webm", "audio/ogg", "audio/mpeg"}
)

# Hard upload ceiling: 10 MiB. Enforced before the provider is called so an
# oversized payload cannot consume provider quota or memory.
ASR_MAX_AUDIO_BYTES: int = 10 * 1024 * 1024

# Hard duration ceiling: 60 seconds. Voice questions are intentionally short;
# longer clips are rejected so the notebook stays focused and provider cost
# stays bounded. The adapter reports ``duration_ms`` which the endpoint checks.
ASR_MAX_DURATION_MS: int = 60_000


class ASRResult(BaseModel):
    """Adapter-level ASR result returned by ``XunfeiAsrAdapter.transcribe``.

    ``transcript`` is the recognized text. ``duration_ms`` is the audio duration
    in milliseconds reported by the provider (or a deterministic stub in mock
    mode). ``confidence``/``language`` are optional because a vendor may decline
    to populate them. ``provider_mode`` is always present so audit logs and the
    response can unambiguously distinguish a MOCK stub from a LIVE result.
    """

    model_config = ConfigDict(extra="forbid")

    transcript: str = Field(min_length=1, max_length=4_000)
    duration_ms: int = Field(ge=0, le=ASR_MAX_DURATION_MS)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    language: str | None = Field(default=None, max_length=32)
    provider_mode: Literal["MOCK", "LIVE"] = "MOCK"


class ASRResponse(BaseModel):
    """Wire response for ``POST /api/v1/asr`` (student-facing).

    Raw audio is NEVER persisted; only audit metadata is recorded. Mirrors
    :class:`ASRResult` field-for-field so the endpoint is a thin adapter that
    validates the MIME/size/duration envelope and forwards the result.
    """

    model_config = ConfigDict(extra="forbid")

    transcript: str = Field(min_length=1, max_length=4_000)
    duration_ms: int = Field(ge=0, le=ASR_MAX_DURATION_MS)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    language: str | None = Field(default=None, max_length=32)
    provider_mode: Literal["MOCK", "LIVE"] = "MOCK"


# The canonical set of keys in a serialized ASRResponse (the wire shape). Tests
# and the generated client assert against this to catch drift.
ASR_RESPONSE_VIEW: frozenset[str] = frozenset(
    {"transcript", "duration_ms", "confidence", "language", "provider_mode"}
)


__all__ = [
    "ASR_ALLOWED_MIME_TYPES",
    "ASR_MAX_AUDIO_BYTES",
    "ASR_MAX_DURATION_MS",
    "ASR_RESPONSE_VIEW",
    "ASRResponse",
    "ASRResult",
]
