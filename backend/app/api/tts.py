"""Student-facing Text-to-Speech endpoint (BE-022).

``POST /api/v1/tts`` synthesizes a short spoken clip from governed text and
returns an authenticated audio URL + subtitle track. Audio is stored in the
private MinIO bucket under the ``resources/tts/`` prefix so the existing
SHA-256 digest governance is reused (BE-007).

Degradation contract: when a live render is requested but no TTS provider is
authorized — and the operator has NOT opted into mock mode — the endpoint
returns a typed ``PROVIDER_UNAVAILABLE`` (HTTP 503) envelope instead of a
half-rendered clip. This keeps the teaching loop unblocked: the caller can fall
back to plain text without confusing a placeholder for a real voice.

Shape mirrors BE-024 (OCR): resolve provider → build adapter → catch the shared
``ProviderAdapterError`` and translate to a typed 503. Mock mode (no credential
or ``PYMENTOR_TTS_MOCK=1``) is the only branch exercised by CI.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.command_idempotency import begin_command, scope_for_request
from app.config import get_settings
from app.contracts.errors import ErrorCode, ErrorEnvelope
from app.contracts.tts import TTSCue, TTSRequest, TTSResponse
from app.db import get_db
from app.evidence import record_audit
from app.idempotency import save_response
from app.models import User
from app.object_store import MinioObjectStore, MinioObjectStoreSettings
from app.observability import record_provider_call
from app.provider_adapters import ProviderAdapterError
from app.provider_adapters.tts_xunfei import (
    MOCK_FLAG,
    TTSResult,
    TTSXunfeiAdapter,
    build_tts_adapter,
)
from app.providers import ProviderType, ResolvedProvider, resolve_enabled_provider
from app.rbac import get_current_user
from app.uow import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/tts", tags=["tts"])

#: Maximum payload size accepted by the endpoint (matches the contract cap).
_MAX_TTS_BYTES = 2 * 1024 * 1024


def _master_key_or_503() -> bytes:
    """Decode the provider master key, mapping absence to a 503."""

    from app.providers import ProviderSecretError, decode_provider_master_key

    try:
        return decode_provider_master_key(get_settings().provider_master_key)
    except ProviderSecretError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provider credential service is unavailable",
        ) from error


def _provider_unavailable_response(request: Request) -> JSONResponse:
    """Typed ``PROVIDER_UNAVAILABLE`` envelope (HTTP 503)."""

    trace_id = str(getattr(request.state, "trace_id", ""))
    envelope = ErrorEnvelope(
        code=ErrorCode.PROVIDER_UNAVAILABLE,
        message="TTS provider is not configured for this tenant.",
        trace_id=trace_id,
        retryable=True,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=envelope.model_dump(mode="json"),
        headers={"x-trace-id": trace_id},
    )


def _object_key(*, tenant_id: UUID, user_id: UUID, request_id: UUID) -> str:
    """Build a versioned, tenant-scoped object key under the governed prefix."""

    return f"resources/tts/{tenant_id}/{user_id}/{request_id}/v1"


def build_tts_object_store() -> MinioObjectStore:
    """Construct the MinIO object store from application settings.

    Exposed as a FastAPI-style factory so tests override it with an in-memory
    fake without monkeypatching module internals.
    """

    return MinioObjectStore(MinioObjectStoreSettings.from_application_settings(get_settings()))


def _resolve_adapter(
    db: Session, *, tenant_id: UUID
) -> tuple[ResolvedProvider | None, TTSXunfeiAdapter]:
    """Resolve the TTS provider + adapter for the tenant.

    Mirrors BE-024 (OCR): the resolved provider (or ``None``) is returned
    alongside the adapter so the caller can label audit rows with the actual
    vendor/model even in mock mode. The ``PYMENTOR_TTS_MOCK=1`` operator flag
    forces mock even when a provider row exists.
    """

    import os

    force_mock = os.environ.get(MOCK_FLAG, "").lower() == "1"
    provider = None
    if not force_mock:
        provider = resolve_enabled_provider(
            db,
            tenant_id=tenant_id,
            provider_type=ProviderType.TTS,
            master_key=_master_key_or_503(),
        )
    return provider, build_tts_adapter(provider)


def _persist_audio(
    object_store: MinioObjectStore,
    *,
    tenant_id: UUID,
    user_id: UUID,
    request_id: UUID,
    result: TTSResult,
) -> tuple[str, str]:
    """Store the synthesized audio in MinIO and return ``(key, digest)``."""

    key = _object_key(tenant_id=tenant_id, user_id=user_id, request_id=request_id)
    stored = object_store.put(
        key=key,
        content=result.audio_bytes,
        mime_type=result.mime,
        version=1,
    )
    return stored.key, stored.digest


def _audio_url(*, request_id: UUID, digest: str) -> str:
    """Authenticated playback route served by this API (never a raw MinIO URL)."""

    return f"/api/v1/tts/audio/{request_id}/{digest}"


def _record_provider_call(
    db: Session,
    *,
    user: User,
    provider: ResolvedProvider | None,
    body: TTSRequest,
    result: TTSResult,
    trace_id: str,
    ok: bool,
    error_code: str | None,
) -> None:
    """Audit + observability for a TTS request."""

    action = "TTS_GENERATED" if ok else "TTS_FAILED"
    record_audit(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action=action,
        resource_type="tts_clip",
        resource_id=trace_id,
        trace_id=trace_id,
        detail={
            "voice": body.voice.value,
            "chars": len(body.text),
            "node_id": str(body.node_id) if body.node_id is not None else None,
            "duration_ms": result.duration_ms,
            "mock": result.mock,
            "error_code": error_code,
        },
    )
    record_provider_call(
        db,
        tenant_id=user.tenant_id,
        provider_type=ProviderType.TTS,
        vendor=(provider.vendor if provider is not None else "mock"),
        model=(provider.model if provider is not None else "mock-tts"),
        operation="TTS_SYNTHESIZE",
        outcome="SUCCEEDED" if ok else "FAILED",
        latency_ms=0,
        rate_limited=False,
        trace_id=trace_id,
        provider_config_id=(provider.id if provider is not None else None),
        input_units=len(body.text),
        output_units=result.duration_ms,
        error_code=error_code,
    )


@router.post("", response_model=TTSResponse)
async def synthesize(
    body: TTSRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    object_store: MinioObjectStore = Depends(build_tts_object_store),
) -> JSONResponse:
    """Synthesize a short spoken clip.

    Idempotent under ``Idempotency-Key`` (replay returns the cached response,
    including the same audio URL + digest). Tenant-scoped: foreign tenants
    cannot read another tenant's clip.
    """

    scope = scope_for_request(request, tenant_id=user.tenant_id, user_id=user.id)
    cached = begin_command(db, scope)
    if cached is not None and cached.response_status is not None:
        return JSONResponse(content=cached.response_body or {}, status_code=cached.response_status)

    provider, adapter = _resolve_adapter(db, tenant_id=user.tenant_id)
    voice_options: dict[str, Any] = {"voice": body.voice.value}
    trace_id = str(request.state.trace_id)
    try:
        result = adapter.generate(body.text, voice_options)
    except ProviderAdapterError as error:
        # Live provider failed (INT-010 NOT-RUN for the live branch). Surface a
        # typed 503 so the teaching loop can degrade to plain text.
        _record_provider_call(
            db,
            user=user,
            provider=provider,
            body=body,
            result=TTSResult(b"", "", 0, [], True),
            trace_id=trace_id,
            ok=False,
            error_code="PROVIDER_FAILED",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TTS provider is unavailable",
        ) from error
    if len(result.audio_bytes) > _MAX_TTS_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="synthesized audio exceeds the maximum accepted size",
        )

    request_id = uuid4()
    object_key, digest = _persist_audio(
        object_store,
        tenant_id=user.tenant_id,
        user_id=user.id,
        request_id=request_id,
        result=result,
    )
    response_body = TTSResponse(
        audio_url=_audio_url(request_id=request_id, digest=digest),
        mime=result.mime,
        duration_ms=result.duration_ms,
        subtitle_track=[
            TTSCue(
                start_ms=int(cue["start_ms"]),
                end_ms=int(cue["end_ms"]),
                text=str(cue["text"]),
            )
            for cue in result.subtitle_track
        ],
        mock=result.mock,
    ).model_dump(mode="json")

    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        _record_provider_call(
            db,
            user=user,
            provider=provider,
            body=body,
            result=result,
            trace_id=trace_id,
            ok=True,
            error_code=None,
        )
        uow.publish(
            event_type="TTS_GENERATED",
            aggregate_type="tts_clip",
            aggregate_id=str(request_id),
            tenant_id=user.tenant_id,
            trace_id=trace_id,
            payload={
                "student_id": str(user.id),
                "node_id": str(body.node_id) if body.node_id is not None else None,
                "voice": body.voice.value,
                "duration_ms": result.duration_ms,
                "object_key": object_key,
                "digest": digest,
                "mock": result.mock,
            },
        )
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_200_OK,
            response_body=response_body,
        )
        uow.commit()
    return JSONResponse(content=response_body, status_code=status.HTTP_200_OK)


@router.get("/audio/{request_id}/{digest}")
async def get_audio(
    request_id: UUID,
    digest: str,
    user: User = Depends(get_current_user),
    object_store: MinioObjectStore = Depends(build_tts_object_store),
) -> Response:
    """Serve the synthesized clip from MinIO.

    The URL is keyed by ``request_id`` (opaque to the caller) AND the SHA-256
    digest of the bytes. Tenant scoping is enforced by reconstructing the
    governed object key from the authenticated user. A mismatched digest is a
    hard 404 (never a different object).
    """

    key = _object_key(tenant_id=user.tenant_id, user_id=user.id, request_id=request_id)
    try:
        content = object_store.read_published(
            key,
            expected_digest=digest,
            max_bytes=_MAX_TTS_BYTES,
        )
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="audio clip not found",
        ) from error
    return Response(
        content=content,
        media_type="audio/wav",
        headers={
            "Cache-Control": "private, max-age=300",
            "ETag": f'"{digest}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = ["router"]
