"""Student-facing OCR endpoint (BE-024).

A student uploads an error screenshot and receives the extracted text. The
upload is transcribed in-memory via the Xunfei OCR adapter (BE-019 resolved
provider, kind=OCR) and **purged**: no raw image is persisted to MinIO. Only
audit/observability metadata (size, mime, provider outcome) is recorded.

Design:

- ``POST /api/v1/ocr`` — student auth, tenant-scoped, multipart form.
- MIME allowlist (png/jpeg/webp) and a hard 5 MiB size cap are enforced at the
  boundary before the provider is called.
- Degraded path: when no OCR provider is enabled for the tenant the adapter
  falls back to mock mode and returns a clearly-labelled stub so the notebook
  flow still works; when a live provider is configured but fails, a typed
  ``PROVIDER_UNAVAILABLE`` error is returned so the caller can branch.

Dependency injection: ``get_ocr_adapter_factory`` returns the zero-arg
``build_ocr_adapter`` factory so FastAPI does not introspect the factory's
``provider`` parameter as a query field. Tests override this dependency to
inject a fake factory (and thus a fake adapter).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.contracts.ocr import (
    OCR_ALLOWED_MIME_TYPES,
    OCR_MAX_IMAGE_BYTES,
    OCRResponse,
)
from app.db import get_db
from app.evidence import record_audit
from app.models import User
from app.observability import record_provider_call
from app.provider_adapters import (
    OcrXunfeiAdapter,
    ProviderAdapterError,
    build_ocr_adapter,
)
from app.providers import (
    ProviderSecretError,
    ProviderType,
    decode_provider_master_key,
    resolve_enabled_provider,
)
from app.rbac import get_current_user

OcrAdapterFactory = Callable[[Any], OcrXunfeiAdapter]

router = APIRouter(prefix="/api/v1/ocr", tags=["ocr"])


def _master_key() -> bytes:
    try:
        return decode_provider_master_key(get_settings().provider_master_key)
    except ProviderSecretError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provider credential service is unavailable",
        ) from error


def get_ocr_adapter_factory() -> OcrAdapterFactory:
    """Return the OCR adapter factory.

    Returning the factory itself (rather than depending on
    ``build_ocr_adapter`` directly) keeps FastAPI from introspecting the
    factory's ``provider`` argument as a query parameter. Tests override this
    dependency to supply a fake factory.
    """

    return build_ocr_adapter


def _normalize_mime(content_type: str | None, filename: str | None) -> str:
    """Pick the MIME type from the multipart ``Content-Type``.

    FastAPI exposes the browser-supplied part Content-Type via
    ``UploadFile.content_type``. We trust it only after the allowlist check so
    a hostile client cannot smuggle an arbitrary type into the provider. When
    the browser omits it we fall back to the filename extension.
    """

    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if not mime and filename:
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
        }.get(suffix, "")
    return mime


def _read_and_validate(file: UploadFile) -> tuple[bytes, str]:
    """Read the upload once, enforcing the MIME allowlist and size cap.

    The body is fully buffered in-memory (bounded by ``OCR_MAX_IMAGE_BYTES``)
    because the Xunfei adapter needs the whole image. Reading is wrapped so a
    truncation or oversize payload surfaces as a 413/415/422 rather than a 500.
    """

    mime = _normalize_mime(file.content_type, file.filename)
    if mime not in OCR_ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(f"unsupported image type: must be one of {sorted(OCR_ALLOWED_MIME_TYPES)}"),
        )
    # Bound the read so an attacker cannot stream gigabytes into memory.
    image_bytes = file.file.read(OCR_MAX_IMAGE_BYTES + 1)
    if len(image_bytes) > OCR_MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(f"image exceeds the {OCR_MAX_IMAGE_BYTES // (1024 * 1024)} MiB limit"),
        )
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="uploaded image is empty",
        )
    return image_bytes, mime


@router.post("", response_model=OCRResponse)
async def transcribe_image(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    adapter_factory: OcrAdapterFactory = Depends(get_ocr_adapter_factory),
) -> JSONResponse:
    """Transcribe an error screenshot to text. No raw image is persisted."""

    image_bytes, mime = _read_and_validate(file)

    provider = resolve_enabled_provider(
        db,
        tenant_id=user.tenant_id,
        provider_type=ProviderType.OCR,
        master_key=_master_key(),
    )
    adapter = adapter_factory(provider)
    trace_id = str(request.state.trace_id)
    try:
        result = adapter.extract(image_bytes, mime)
    except ProviderAdapterError as error:
        # Live provider failed: record the outcome and surface a typed 503 so
        # the notebook can degrade (the student still has the error text they
        # were about to paste).
        _record_provider_call(
            db,
            user=user,
            provider=provider,
            mime=mime,
            size_bytes=len(image_bytes),
            trace_id=trace_id,
            ok=False,
            error_code="PROVIDER_FAILED",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OCR provider is unavailable",
        ) from error

    _record_provider_call(
        db,
        user=user,
        provider=provider,
        mime=mime,
        size_bytes=len(image_bytes),
        trace_id=trace_id,
        ok=True,
        error_code=None,
    )
    response = OCRResponse(
        extracted_text=result.text,
        confidence=result.confidence,
        mime=mime,
        size_bytes=len(image_bytes),
    )
    db.commit()
    # ``image_bytes`` goes out of scope here; nothing in this request path
    # persists it. The explicit ``del`` documents the purge intent for readers.
    del image_bytes
    return JSONResponse(
        content=response.model_dump(mode="json"),
        status_code=status.HTTP_200_OK,
    )


def _record_provider_call(
    db: Session,
    *,
    user: User,
    provider: Any,
    mime: str,
    size_bytes: int,
    trace_id: str,
    ok: bool,
    error_code: str | None,
) -> None:
    """Audit + observability for an OCR request (no raw image retained)."""

    action = "OCR_EXTRACTED" if ok else "OCR_FAILED"
    record_audit(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action=action,
        resource_type="ocr_request",
        resource_id=trace_id,
        trace_id=trace_id,
        detail={
            "mime": mime,
            "size_bytes": size_bytes,
            "provider_mode": "MOCK" if provider is None else "LIVE",
            "error_code": error_code,
        },
    )
    record_provider_call(
        db,
        tenant_id=user.tenant_id,
        provider_type=ProviderType.OCR,
        vendor=(provider.vendor if provider is not None else "mock"),
        model=(provider.model if provider is not None else "mock-ocr"),
        operation="OCR_EXTRACT",
        outcome="SUCCEEDED" if ok else "FAILED",
        latency_ms=0,
        rate_limited=False,
        trace_id=trace_id,
        provider_config_id=(provider.id if provider is not None else None),
        input_units=size_bytes,
        error_code=error_code,
    )


__all__ = ["get_ocr_adapter_factory", "router"]
