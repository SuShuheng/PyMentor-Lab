"""Strict wire contracts for the student-facing TTS endpoint (BE-022).

The contract is intentionally narrow: it surfaces the audio URL, the subtitle
track (so the renderer can paint captions aligned to the synthesized audio), the
MIME type, and the duration. ``mock`` MUST always be present so the renderer can
visually distinguish a placeholder clip from a real synthesized voice (design
§10.4: native protocol wrapped behind the provider abstraction).
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TTSVoice(StrEnum):
    """Stable voice identifiers surfaced to the renderer.

    The Xunfei backend model/appId mapping lives entirely inside the adapter;
    the API only accepts this small, controlled enum so the wire contract is
    independent of vendor-specific voice names.
    """

    XIAOYAN = "xiaoyan"
    XIAOYU = "xiaoyu"


class TTSCue(BaseModel):
    """A single subtitle cue aligned to the synthesized audio."""

    model_config = ConfigDict(extra="forbid")

    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=512)


class TTSRequest(BaseModel):
    """``POST /api/v1/tts`` body."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)
    voice: TTSVoice = Field(default=TTSVoice.XIAOYAN)
    node_id: UUID | None = Field(
        default=None,
        description=(
            "Optional governed course-node binding so the generated clip is "
            "attributable to a teaching context in audit logs."
        ),
    )


class TTSResponse(BaseModel):
    """``POST /api/v1/tts`` response.

    ``audio_url`` is an authenticated, tenant-scoped route served by the API
    itself; the renderer never talks to MinIO directly. ``mock`` is always
    present and is ``True`` whenever the adapter produced a deterministic stub
    (no live credential authorized or PYMENTOR_TTS_MOCK=1).
    """

    model_config = ConfigDict(extra="forbid")

    audio_url: str
    mime: str
    duration_ms: int = Field(ge=0)
    subtitle_track: list[TTSCue]
    mock: bool


__all__ = ["TTSCue", "TTSRequest", "TTSResponse", "TTSVoice"]
