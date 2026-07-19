"""Xunfei OCR provider adapter (BE-024).

This is the OCR twin of the BE-019 provider abstraction. It reads a resolved
``ResolvedProvider`` (``provider_type == OCR``) and exposes a single
``extract(image_bytes, mime) -> OCRResult`` entry point.

Two modes are supported (see ``provider_adapters.__init__``):

- **Mock mode** (default) — when no enabled OCR ``provider_configs`` row exists
  for the tenant, or when ``PYMENTOR_OCR_MOCK=1`` is set. Returns a
  deterministic stub transcription so notebook flows work without a live
  dependency. This is the only mode exercised by unit tests.
- **Live mode** — when a real credential is authorized. The adapter posts to
  the Xunfei OCR endpoint; transport/upstream failures surface as
  ``ProviderAdapterError``. Live verification is tracked as INT-010 NOT-RUN.

Shape is identical to BE-022 (TTS) and BE-025 (ASR): a module per vendor, a
single ``extract*`` entry point, shared typed errors, and the shared
``mock_mode_enabled`` helper.
"""

from __future__ import annotations

import hashlib

from app.contracts.ocr import OCRResult
from app.provider_adapters import (
    ProviderAdapterError,
    mock_mode_enabled,
)
from app.providers import ResolvedProvider

_MOCK_FLAG = "PYMENTOR_OCR_MOCK"


def _mock_transcription(image_bytes: bytes, mime: str) -> OCRResult:
    """Deterministic stub transcription for mock mode.

    The text is stable for a given payload so tests can assert on it without
    depending on a live upstream. A short digest suffix lets callers verify
    the right bytes were processed without echoing them back.
    """

    digest = hashlib.sha256(image_bytes).hexdigest()[:8]
    return OCRResult(
        text=(f"[mock-ocr] mime={mime} bytes={len(image_bytes)} digest={digest}"),
        confidence=0.97,
        bboxes=[],
    )


class OcrXunfeiAdapter:
    """Adapter for the Xunfei (iFlytek) OCR provider.

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

    def extract(self, image_bytes: bytes, mime: str) -> OCRResult:
        """Transcribe ``image_bytes`` (declared ``mime``) to ``OCRResult``."""

        if self.is_mock:
            return _mock_transcription(image_bytes, mime)

        # Live path (exercised only by INT-010 against the real upstream).
        assert self._provider is not None
        try:
            return self._extract_live(image_bytes, mime)
        except ProviderAdapterError:
            raise
        except Exception as error:  # pragma: no cover - live path only
            raise ProviderAdapterError("Xunfei OCR request failed") from error

    def _extract_live(
        self, image_bytes: bytes, mime: str
    ) -> OCRResult:  # pragma: no cover - live path
        """Live Xunfei OCR call.

        Gated behind ``is_mock is False`` and only exercised by INT-010.
        The implementation will sign and post per Xunfei's WebAPI when a live
        credential is available; for now it fails closed instead of returning
        fake text.
        """

        raise ProviderAdapterError("Xunfei OCR live mode is not configured")


def build_ocr_adapter(provider: ResolvedProvider | None) -> OcrXunfeiAdapter:
    """Factory used by the API layer; tests override this for fakes."""

    return OcrXunfeiAdapter(provider)


__all__ = [
    "OcrXunfeiAdapter",
    "build_ocr_adapter",
]
