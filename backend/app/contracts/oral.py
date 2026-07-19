"""Strict contracts for the oral-explanation scoring endpoint (BE-026).

The endpoint composes BE-022 (TTS prompt synthesis) + BE-025 (ASR capture) +
an LLM rubric to score a student's verbal explanation of a concept. The result
is recorded as evidence (event type ``ORAL_EXPLANATION_SCORED``) and projected
to the ``INDEPENDENCE_SUPPORT`` profile dimension at low confidence (design
§8.3: oral explanations are an independence/explanation signal). It NEVER
auto-advances mastery — that decision is owned exclusively by the assessment
pipeline (CONTRACT rule).

Mock vs. live parity with BE-022 / BE-025: a ``mock`` flag must always be
present and ``True`` whenever a stage produced a deterministic stub (no live
credential authorized or the relevant ``PYMENTOR_*_MOCK=1`` is set). Live
verification is tracked separately as INT-010 NOT-RUN; tests never exercise the
live branch.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# MIME types accepted for the student's recorded explanation upload. Mirrors the
# BE-025 ASR allowlist so the same recorder clients work unchanged.
ORAL_ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {"audio/wav", "audio/x-wav", "audio/wave", "audio/webm", "audio/ogg", "audio/mpeg"}
)

# Hard upload ceiling: 10 MiB (same rationale as ASR — bound memory + provider
# quota before transcription). Enforced at the boundary.
ORAL_MAX_AUDIO_BYTES: int = 10 * 1024 * 1024

# Hard duration ceiling on the captured explanation: 120 seconds. Explanations
# are intentionally longer than a short ASR question, so the cap is twice the
# BE-025 limit. Enforced on the adapter-reported ``duration_ms``.
ORAL_MAX_DURATION_MS: int = 120_000

# Hard caps on the governed prompt text fed to TTS. Mirrors the BE-022 limit so
# a placeholder prompt clip stays bounded.
ORAL_MAX_PROMPT_CHARS: int = 2_000


class OralTTSStage(BaseModel):
    """The synthesized TTS prompt stage (mock = silent WAV + subtitle)."""

    model_config = ConfigDict(extra="forbid")

    audio_url: str = Field(min_length=1)
    mime: str = Field(min_length=1)
    duration_ms: int = Field(ge=0)
    mock: bool


class OralTranscriptStage(BaseModel):
    """The ASR transcription of the student's recorded explanation."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4_000)
    duration_ms: int = Field(ge=0, le=ORAL_MAX_DURATION_MS)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    language: str | None = Field(default=None, max_length=32)
    provider_mode: Literal["MOCK", "LIVE"] = "MOCK"


class OralRubricItem(BaseModel):
    """A single scored rubric criterion from the LLM rubric (mock or live)."""

    model_config = ConfigDict(extra="forbid")

    criterion: str = Field(min_length=1, max_length=64)
    score: float = Field(ge=0.0, le=1.0)
    feedback: str = Field(min_length=1, max_length=2_000)


class OralExplanationResponse(BaseModel):
    """Wire response for ``POST /api/v1/oral-explanation`` (student-facing).

    ``prompt`` is the TTS-synthesized question clip (mock = silent placeholder).
    ``transcript`` is the ASR of the student's explanation. ``rubric`` is the
    LLM-graded breakdown. ``score`` is the aggregate score. ``model_answer`` is
    a short canonical answer for comparison. ``evidence_id`` is the
    ``ORAL_EXPLANATION_SCORED`` event id. ``mock`` MUST always be present and is
    ``True`` whenever ANY stage produced a deterministic stub.
    """

    model_config = ConfigDict(extra="forbid")

    prompt: OralTTSStage
    transcript: OralTranscriptStage
    rubric: list[OralRubricItem] = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    model_answer: str = Field(min_length=1, max_length=4_000)
    evidence_id: str = Field(min_length=1, max_length=128)
    mock: bool


# Canonical set of keys in a serialized OralExplanationResponse. Tests assert
# against this to catch drift in the wire shape.
ORAL_RESPONSE_VIEW: frozenset[str] = frozenset(
    {"prompt", "transcript", "rubric", "score", "model_answer", "evidence_id", "mock"}
)


__all__ = [
    "ORAL_ALLOWED_MIME_TYPES",
    "ORAL_MAX_AUDIO_BYTES",
    "ORAL_MAX_DURATION_MS",
    "ORAL_MAX_PROMPT_CHARS",
    "ORAL_RESPONSE_VIEW",
    "OralExplanationResponse",
    "OralRubricItem",
    "OralTTSStage",
    "OralTranscriptStage",
]
