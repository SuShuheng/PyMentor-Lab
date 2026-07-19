"""Student-facing ASR endpoint (BE-025).

A student records a voice question and receives the transcribed text, which
feeds into the BE-007 Q&A flow. The upload is transcribed in-memory via the
Xunfei ASR adapter (BE-019 resolved provider, kind=ASR) and **purged**: no raw
audio is persisted. Only audit/observability metadata (size, mime, duration,
provider outcome) is recorded.

Design:

- ``POST /api/v1/asr`` — student auth, tenant-scoped, multipart form.
- MIME allowlist (wav/webm/ogg/mp3) and a hard 10 MiB size cap are enforced at
  the boundary before the provider is called; a 60s duration cap is enforced on
  the adapter-reported ``duration_ms``.
- Degraded path: when no ASR provider is enabled for the tenant the adapter
  falls back to mock mode and returns a clearly-labelled stub so the notebook
  flow still works; when a live provider is configured but fails, a typed
  ``PROVIDER_UNAVAILABLE`` error is returned so the student can always fall back
  to typing the question.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.contracts.asr import (
    ASR_ALLOWED_MIME_TYPES,
    ASR_MAX_AUDIO_BYTES,
    ASR_MAX_DURATION_MS,
    ASRResponse,
)
from app.db import get_db
from app.evidence import record_audit
from app.models import User
from app.observability import record_provider_call
from app.provider_adapters import (
    ProviderAdapterError,
    XunfeiAsrAdapter,
    build_asr_adapter,
)
from app.providers import (
    ProviderSecretError,
    ProviderType,
    decode_provider_master_key,
    resolve_enabled_provider,
)
from app.rbac import get_current_user

router = APIRouter(prefix="/api/v1/asr", tags=["asr"])

# Callable type of the adapter factory exposed for dependency injection. A thin
# provider function (``get_asr_adapter_builder``) returns the factory so tests
# can override the builder via ``app.dependency_overrides`` without FastAPI
# treating the factory's ``provider`` argument as a request query parameter
# (which is what happens if the factory itself is used as a ``Depends``).
AsrAdapterFactory = Any


def _master_key() -> bytes:
    try:
        return decode_provider_master_key(get_settings().provider_master_key)
    except ProviderSecretError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provider credential service is unavailable",
        ) from error


def get_asr_adapter_builder() -> AsrAdapterFactory:
    """Dependency provider for the ASR adapter factory.

    Returns :func:`build_asr_adapter` by default; tests override this via
    ``app.dependency_overrides[get_asr_adapter_builder]`` to inject a fake
    adapter (mirrors ``get_provider_probe`` in ``api.providers``).
    """

    return build_asr_adapter


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
            "wav": "audio/wav",
            "webm": "audio/webm",
            "ogg": "audio/ogg",
            "oga": "audio/ogg",
            "mp3": "audio/mpeg",
            "mpga": "audio/mpeg",
            "mp2": "audio/mpeg",
        }.get(suffix, "")
    return mime


def _read_and_validate(file: UploadFile) -> tuple[bytes, str]:
    """Read the upload once, enforcing the MIME allowlist and size cap.

    The body is fully buffered in-memory (bounded by
    :data:`ASR_MAX_AUDIO_BYTES`) because the Xunfei adapter needs the whole
    clip. Reading is wrapped so a truncation or oversize payload surfaces as a
    413/415/422 rather than a 500.
    """

    mime = _normalize_mime(file.content_type, file.filename)
    if mime not in ASR_ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(f"unsupported audio type: must be one of {sorted(ASR_ALLOWED_MIME_TYPES)}"),
        )
    # Bound the read so an attacker cannot stream gigabytes into memory.
    audio_bytes = file.file.read(ASR_MAX_AUDIO_BYTES + 1)
    if len(audio_bytes) > ASR_MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(f"audio exceeds the {ASR_MAX_AUDIO_BYTES // (1024 * 1024)} MiB limit"),
        )
    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="uploaded audio is empty",
        )
    return audio_bytes, mime


@router.post("", response_model=ASRResponse)
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    build_adapter: AsrAdapterFactory = Depends(get_asr_adapter_builder),
) -> JSONResponse:
    """Transcribe a voice question to text. No raw audio is persisted.

    The returned ``transcript`` is intended to feed directly into the BE-007
    Q&A flow as a ``user`` message. The raw audio is purged immediately after
    transcription; only audit metadata (mime, size, duration, provider mode)
    is retained.
    """

    audio_bytes, mime = _read_and_validate(file)

    provider = resolve_enabled_provider(
        db,
        tenant_id=user.tenant_id,
        provider_type=ProviderType.ASR,
        master_key=_master_key(),
    )
    adapter = build_adapter(provider)
    trace_id = str(request.state.trace_id)
    try:
        result = adapter.transcribe(audio_bytes, mime)
    except ProviderAdapterError as error:
        # Live provider failed: record the outcome and surface a typed 503 so
        # the notebook can degrade (the student can always type the question).
        _record_provider_call(
            db,
            user=user,
            provider=provider,
            mime=mime,
            size_bytes=len(audio_bytes),
            duration_ms=None,
            trace_id=trace_id,
            ok=False,
            error_code="PROVIDER_FAILED",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ASR provider is unavailable",
        ) from error

    if result.duration_ms > ASR_MAX_DURATION_MS:
        # Duration cap is enforced after transcription because the adapter
        # reports it; reject before persisting a successful-but-too-long result.
        _record_provider_call(
            db,
            user=user,
            provider=provider,
            mime=mime,
            size_bytes=len(audio_bytes),
            duration_ms=result.duration_ms,
            trace_id=trace_id,
            ok=False,
            error_code="DURATION_LIMIT",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(f"audio duration exceeds the {ASR_MAX_DURATION_MS // 1000}s limit"),
        )

    _record_provider_call(
        db,
        user=user,
        provider=provider,
        mime=mime,
        size_bytes=len(audio_bytes),
        duration_ms=result.duration_ms,
        trace_id=trace_id,
        ok=True,
        error_code=None,
    )
    response = ASRResponse(
        transcript=result.transcript,
        duration_ms=result.duration_ms,
        confidence=result.confidence,
        language=result.language,
        provider_mode=result.provider_mode,
    )
    db.commit()
    # ``audio_bytes`` goes out of scope here; nothing in this request path
    # persists it. The explicit ``del`` documents the purge intent for readers.
    del audio_bytes
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
    duration_ms: int | None,
    trace_id: str,
    ok: bool,
    error_code: str | None,
) -> None:
    """Audit + observability for an ASR request (no raw audio retained).

    Records ONLY metadata — mime, size, duration, provider mode/outcome — never
    the audio bytes or the transcript text (the transcript is returned to the
    caller over the wire but is not audit-logged here).
    """

    action = "ASR_TRANSCRIPTION" if ok else "ASR_FAILED"
    record_audit(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action=action,
        resource_type="asr",
        resource_id=trace_id,
        trace_id=trace_id,
        detail={
            "mime": mime,
            "size_bytes": size_bytes,
            "duration_ms": duration_ms,
            "provider_mode": "MOCK" if provider is None else "LIVE",
            "error_code": error_code,
        },
    )
    record_provider_call(
        db,
        tenant_id=user.tenant_id,
        provider_type=ProviderType.ASR,
        vendor=(provider.vendor if provider is not None else "mock"),
        model=(provider.model if provider is not None else "mock-asr"),
        operation="ASR_TRANSCRIBE",
        outcome="SUCCEEDED" if ok else "FAILED",
        latency_ms=0,
        rate_limited=False,
        trace_id=trace_id,
        provider_config_id=(provider.id if provider is not None else None),
        input_units=size_bytes,
        error_code=error_code,
    )


__all__ = ["XunfeiAsrAdapter", "build_asr_adapter", "get_asr_adapter_builder", "router"]
