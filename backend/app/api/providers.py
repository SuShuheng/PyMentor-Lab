"""System Admin-only encrypted Provider configuration routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.command_idempotency import begin_command, scope_for_request
from app.config import get_settings
from app.contracts.providers import (
    ProviderConfigCreate,
    ProviderConfigPage,
    ProviderConfigUpdate,
    ProviderConfigView,
    ProviderConnectivityView,
)
from app.db import get_db
from app.evidence import record_audit
from app.idempotency import save_response
from app.models import ProviderConfig, User
from app.observability import record_provider_call
from app.providers import (
    ProviderSecretError,
    decode_provider_master_key,
    decrypt_provider_secret,
    disable_other_providers,
    encrypt_provider_secret,
    mask_provider_secret,
    provider_secret_context,
)
from app.rbac import require_system_admin
from app.uow import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/admin/providers", tags=["admin-providers"])


@dataclass(frozen=True, slots=True)
class ProviderProbe:
    ok: bool
    latency_ms: int
    status_code: int | None
    detail: str


ProviderProbeCallable = Callable[[str, str], ProviderProbe]


def probe_provider(endpoint: str, api_key: str) -> ProviderProbe:
    """Perform a bounded, non-redirecting reachability/authentication probe."""
    started = perf_counter()
    try:
        response = httpx.get(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=5.0,
            follow_redirects=False,
        )
    except httpx.TimeoutException:
        return ProviderProbe(False, int((perf_counter() - started) * 1000), None, "timeout")
    except httpx.HTTPError:
        return ProviderProbe(
            False, int((perf_counter() - started) * 1000), None, "connection failed"
        )
    latency_ms = int((perf_counter() - started) * 1000)
    ok = response.status_code < 400
    if response.status_code in (401, 403):
        detail = "credentials rejected"
    elif ok:
        detail = "reachable"
    else:
        detail = "provider returned an error"
    return ProviderProbe(ok, latency_ms, response.status_code, detail)


def get_provider_probe() -> ProviderProbeCallable:
    return probe_provider


def _master_key() -> bytes:
    try:
        return decode_provider_master_key(get_settings().provider_master_key)
    except ProviderSecretError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provider credential service is unavailable",
        ) from error


def _scoped_config(db: Session, *, tenant_id: UUID, provider_id: UUID) -> ProviderConfig:
    config = db.scalar(
        select(ProviderConfig).where(
            ProviderConfig.id == provider_id,
            ProviderConfig.tenant_id == tenant_id,
        )
    )
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    return config


def _view(config: ProviderConfig, master_key: bytes) -> ProviderConfigView:
    secret = decrypt_provider_secret(
        config.api_key_encrypted,
        master_key,
        provider_secret_context(config.tenant_id, config.id),
    )
    return ProviderConfigView(
        id=config.id,
        provider_type=config.provider_type,
        vendor=config.vendor,
        model=config.model,
        api_key_masked=mask_provider_secret(secret),
        endpoint=config.endpoint,
        params=config.params,
        enabled=config.enabled,
        version=config.version,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def _cached_response(cached: object) -> JSONResponse | None:
    response_status = getattr(cached, "response_status", None)
    if cached is not None and response_status is not None:
        return JSONResponse(
            content=getattr(cached, "response_body", None) or {},
            status_code=response_status,
        )
    return None


@router.get("", response_model=ProviderConfigPage)
async def list_providers(
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> ProviderConfigPage:
    master_key = _master_key()
    configs = list(
        db.scalars(
            select(ProviderConfig)
            .where(ProviderConfig.tenant_id == admin.tenant_id)
            .order_by(ProviderConfig.provider_type, ProviderConfig.created_at, ProviderConfig.id)
        )
    )
    return ProviderConfigPage(items=[_view(config, master_key) for config in configs])


@router.post("", response_model=ProviderConfigView, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderConfigCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> JSONResponse:
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cached_response(begin_command(db, scope))
    if cached_response is not None:
        return cached_response
    master_key = _master_key()
    provider_id = uuid4()
    config = ProviderConfig(
        id=provider_id,
        tenant_id=admin.tenant_id,
        provider_type=body.provider_type,
        vendor=body.vendor,
        model=body.model,
        api_key_encrypted=encrypt_provider_secret(
            body.api_key.get_secret_value(),
            master_key,
            provider_secret_context(admin.tenant_id, provider_id),
        ),
        endpoint=None if body.endpoint is None else str(body.endpoint),
        params=body.params,
        enabled=body.enabled,
    )
    trace_id = str(request.state.trace_id)
    try:
        with SqlAlchemyUnitOfWork(accept_session=db) as uow:
            if config.enabled:
                disable_other_providers(
                    db,
                    tenant_id=admin.tenant_id,
                    provider_type=config.provider_type,
                    except_id=config.id,
                )
            db.add(config)
            db.flush()
            response_body = _view(config, master_key).model_dump(mode="json")
            record_audit(
                db,
                tenant_id=admin.tenant_id,
                actor_user_id=admin.id,
                action="PROVIDER_CONFIG_CREATED",
                resource_type="provider_config",
                resource_id=str(config.id),
                trace_id=trace_id,
                detail={
                    "provider_type": config.provider_type.value,
                    "vendor": config.vendor,
                    "model": config.model,
                    "enabled": config.enabled,
                },
            )
            uow.publish(
                event_type="PROVIDER_CONFIG_CHANGED",
                aggregate_type="provider_config",
                aggregate_id=str(config.id),
                tenant_id=admin.tenant_id,
                trace_id=trace_id,
                payload={"provider_type": config.provider_type.value, "version": config.version},
            )
            save_response(
                db,
                key=scope.key,
                response_status=status.HTTP_201_CREATED,
                response_body=response_body,
            )
            uow.commit()
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider identity or enabled type already exists",
        ) from error
    return JSONResponse(content=response_body, status_code=status.HTTP_201_CREATED)


@router.patch("/{provider_id}", response_model=ProviderConfigView)
async def update_provider(
    provider_id: UUID,
    body: ProviderConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> JSONResponse:
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cached_response(begin_command(db, scope))
    if cached_response is not None:
        return cached_response
    master_key = _master_key()
    config = _scoped_config(db, tenant_id=admin.tenant_id, provider_id=provider_id)
    changed_fields = sorted(body.model_fields_set)
    if "vendor" in body.model_fields_set:
        assert body.vendor is not None
        config.vendor = body.vendor
    if "model" in body.model_fields_set:
        assert body.model is not None
        config.model = body.model
    if "api_key" in body.model_fields_set:
        assert body.api_key is not None
        config.api_key_encrypted = encrypt_provider_secret(
            body.api_key.get_secret_value(),
            master_key,
            provider_secret_context(config.tenant_id, config.id),
        )
    if "endpoint" in body.model_fields_set:
        config.endpoint = None if body.endpoint is None else str(body.endpoint)
    if "params" in body.model_fields_set:
        assert body.params is not None
        config.params = body.params
    if "enabled" in body.model_fields_set:
        assert body.enabled is not None
        config.enabled = body.enabled
    config.version += 1
    trace_id = str(request.state.trace_id)
    try:
        with SqlAlchemyUnitOfWork(accept_session=db) as uow:
            if config.enabled:
                disable_other_providers(
                    db,
                    tenant_id=admin.tenant_id,
                    provider_type=config.provider_type,
                    except_id=config.id,
                )
            db.flush()
            response_body = _view(config, master_key).model_dump(mode="json")
            record_audit(
                db,
                tenant_id=admin.tenant_id,
                actor_user_id=admin.id,
                action="PROVIDER_CONFIG_UPDATED",
                resource_type="provider_config",
                resource_id=str(config.id),
                trace_id=trace_id,
                detail={"changed_fields": changed_fields, "version": config.version},
            )
            uow.publish(
                event_type="PROVIDER_CONFIG_CHANGED",
                aggregate_type="provider_config",
                aggregate_id=str(config.id),
                tenant_id=admin.tenant_id,
                trace_id=trace_id,
                payload={"provider_type": config.provider_type.value, "version": config.version},
            )
            save_response(
                db,
                key=scope.key,
                response_status=status.HTTP_200_OK,
                response_body=response_body,
            )
            uow.commit()
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider identity or enabled type already exists",
        ) from error
    return JSONResponse(content=response_body, status_code=status.HTTP_200_OK)


@router.post("/{provider_id}/test", response_model=ProviderConnectivityView)
async def test_provider_connectivity(
    provider_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
    probe: ProviderProbeCallable = Depends(get_provider_probe),
) -> JSONResponse:
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cached_response(begin_command(db, scope))
    if cached_response is not None:
        return cached_response
    master_key = _master_key()
    config = _scoped_config(db, tenant_id=admin.tenant_id, provider_id=provider_id)
    if config.endpoint is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider endpoint is not configured",
        )
    api_key = decrypt_provider_secret(
        config.api_key_encrypted,
        master_key,
        provider_secret_context(config.tenant_id, config.id),
    )
    result = probe(config.endpoint, api_key)
    view = ProviderConnectivityView(
        ok=result.ok,
        latency_ms=result.latency_ms,
        status_code=result.status_code,
        detail=result.detail,
    )
    response_body = view.model_dump(mode="json")
    trace_id = str(request.state.trace_id)
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        record_provider_call(
            db,
            tenant_id=admin.tenant_id,
            provider_config_id=config.id,
            provider_type=config.provider_type,
            vendor=config.vendor,
            model=config.model,
            operation="CONNECTIVITY_TEST",
            outcome="SUCCEEDED" if result.ok else "FAILED",
            latency_ms=result.latency_ms,
            rate_limited=result.status_code == 429,
            status_code=result.status_code,
            error_code=None if result.ok else "CONNECTIVITY_FAILED",
            trace_id=trace_id,
        )
        record_audit(
            db,
            tenant_id=admin.tenant_id,
            actor_user_id=admin.id,
            action="PROVIDER_CONNECTIVITY_TESTED",
            resource_type="provider_config",
            resource_id=str(config.id),
            trace_id=trace_id,
            detail={
                "ok": result.ok,
                "latency_ms": result.latency_ms,
                "status_code": result.status_code,
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
