"""Strict contracts for student-facing OCR (BE-024).

A student uploads an error screenshot and receives the extracted text.
No raw image is persisted: the upload is transcribed in-memory and purged;
only audit/observability metadata (size, mime, provider outcome) is recorded.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# MIME types accepted for OCR uploads. The allowlist is deliberately narrow
# (raster images only) and applied at the boundary along with a hard size cap.
OCR_ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/webp"}
)

# Hard upload ceiling: 5 MiB. Enforced before the provider is called so an
# oversized payload cannot consume provider quota or memory.
OCR_MAX_IMAGE_BYTES: int = 5 * 1024 * 1024


class OCRResult(BaseModel):
    """Adapter-level OCR result returned by ``OcrXunfeiAdapter.extract``.

    ``text`` is the plain transcription. ``confidence`` is the optional
    provider-reported score in ``[0, 1]``. ``bboxes`` is an optional list of
    bounding boxes for downstream rendering and is empty when the provider does
    not return layout data.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=0, max_length=16_384)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    bboxes: list[dict[str, object]] = Field(default_factory=list)


class OCRResponse(BaseModel):
    """Wire response for ``POST /api/v1/ocr`` (student-facing)."""

    model_config = ConfigDict(extra="forbid")

    extracted_text: str = Field(min_length=0, max_length=16_384)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    mime: str = Field(min_length=1, max_length=64)
    size_bytes: int = Field(ge=0, le=OCR_MAX_IMAGE_BYTES)


__all__ = [
    "OCR_ALLOWED_MIME_TYPES",
    "OCR_MAX_IMAGE_BYTES",
    "OCRResponse",
    "OCRResult",
]
