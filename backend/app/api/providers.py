"""System Admin-only encrypted Provider configuration routes.

BE-019 full surface (design §17.4):

- ``GET /`` and ``GET /{id}`` — list/detail with masked keys.
- ``POST /`` — create (encrypt key); ``PATCH /{id}`` — update (re-encrypt on key change).
- ``DELETE /{id}`` — soft delete (``enabled=False``); the row is preserved for audit
  and the foreign-key history of ``provider_calls``. Hard-delete is intentionally
  refused so audit and observability retain referential integrity.
- ``POST /{id}/enable`` and ``POST /{id}/disable`` — explicit, idempotent toggles
  with dedicated audit actions (``PROVIDER_CONFIG_ENABLED`` / _DISABLED). The
  ``enabled`` field on ``PATCH`` remains for general updates; both paths enforce
  the §17.4 invariant: at most one enabled provider per ``(tenant, type)``.

Switch semantics: a switch takes effect on NEW tasks; in-flight tasks keep using
the configuration captured at start time (see ``resolve_enabled_provider``).
"""

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
    ProviderConnectivityTestRequest,
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


@router.get("/{provider_id}", response_model=ProviderConfigView)
async def get_provider(
    provider_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> ProviderConfigView:
    """Fetch a single Provider configuration with the key masked.

    Reads are not idempotency-keyed (they are side-effect free and cacheable).
    Tenant scoping is enforced by ``_scoped_config`` (foreign tenant → 404).
    """
    master_key = _master_key()
    config = _scoped_config(db, tenant_id=admin.tenant_id, provider_id=provider_id)
    return _view(config, master_key)


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
    body: ProviderConnectivityTestRequest | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
    probe: ProviderProbeCallable = Depends(get_provider_probe),
) -> JSONResponse:
    """Run a bounded connectivity probe and return the standardized result.

    BE-019: the response shape is ``{ok, latency_ms, status_code, detail,
    model_id, error_code}``. The API key is NEVER echoed. If a candidate
    ``api_key`` is supplied in the body it is used INSTEAD of the stored key
    (pre-save rotation validation) and is NOT persisted. Without a body the
    currently stored key is tested.
    """
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
    if body is not None and body.api_key is not None:
        api_key = body.api_key.get_secret_value()
    else:
        api_key = decrypt_provider_secret(
            config.api_key_encrypted,
            master_key,
            provider_secret_context(config.tenant_id, config.id),
        )
    result = probe(config.endpoint, api_key)
    error_code = None if result.ok else "CONNECTIVITY_FAILED"
    view = ProviderConnectivityView(
        ok=result.ok,
        latency_ms=result.latency_ms,
        status_code=result.status_code,
        detail=result.detail,
        model_id=config.model,
        error_code=error_code,
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
            error_code=error_code,
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
                "error_code": error_code,
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


def _finalize_provider_command(
    *,
    db: Session,
    uow: SqlAlchemyUnitOfWork,
    admin: User,
    config: ProviderConfig,
    master_key: bytes,
    trace_id: str,
    scope_key: str,
    audit_action: str,
    event_payload: dict[str, object],
    extra_audit_detail: dict[str, object] | None = None,
) -> dict[str, object]:
    """Inside-UoW finalize: audit + outbox + idempotency + commit.

    Called from within the ``with SqlAlchemyUnitOfWork(accept_session=db) as uow``
    block in each command endpoint so that the pre-commit work (e.g. clearing
    the enabled-type slot) shares the same transaction.
    """
    response_body = _view(config, master_key).model_dump(mode="json")
    audit_detail: dict[str, object] = {
        "provider_type": config.provider_type.value,
        "enabled": config.enabled,
        "version": config.version,
    }
    if extra_audit_detail:
        audit_detail.update(extra_audit_detail)
    record_audit(
        db,
        tenant_id=admin.tenant_id,
        actor_user_id=admin.id,
        action=audit_action,
        resource_type="provider_config",
        resource_id=str(config.id),
        trace_id=trace_id,
        detail=audit_detail,
    )
    uow.publish(
        event_type="PROVIDER_CONFIG_CHANGED",
        aggregate_type="provider_config",
        aggregate_id=str(config.id),
        tenant_id=admin.tenant_id,
        trace_id=trace_id,
        payload=event_payload,
    )
    save_response(
        db,
        key=scope_key,
        response_status=status.HTTP_200_OK,
        response_body=response_body,
    )
    uow.commit()
    return response_body


@router.post("/{provider_id}/enable", response_model=ProviderConfigView)
async def enable_provider(
    provider_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> JSONResponse:
    """Enable a provider and switch the per-type slot to it (design §17.4).

    Dedicated action for explicit UI intent and a distinct ``PROVIDER_CONFIG_ENABLED``
    audit row. Idempotent under ``Idempotency-Key``: a replay returns the cached
    response. Enabling an already-enabled row still bumps the version and audits.
    Switch semantics: in-flight tasks keep their captured config; only newly
    started tasks pick up the newly enabled provider.
    """
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cached_response(begin_command(db, scope))
    if cached_response is not None:
        return cached_response
    master_key = _master_key()
    config = _scoped_config(db, tenant_id=admin.tenant_id, provider_id=provider_id)
    config.enabled = True
    config.version += 1
    trace_id = str(request.state.trace_id)
    try:
        with SqlAlchemyUnitOfWork(accept_session=db) as uow:
            # Pre-commit: clear the enabled slot for this (tenant, type) before
            # flushing the now-enabled row, to keep the partial unique index
            # satisfied. The audit/commit happens in the shared helper below
            # within the SAME transaction.
            disable_other_providers(
                db,
                tenant_id=admin.tenant_id,
                provider_type=config.provider_type,
                except_id=config.id,
            )
            response_body = _finalize_provider_command(
                db=db,
                uow=uow,
                admin=admin,
                config=config,
                master_key=master_key,
                trace_id=trace_id,
                scope_key=scope.key,
                audit_action="PROVIDER_CONFIG_ENABLED",
                event_payload={
                    "provider_type": config.provider_type.value,
                    "version": config.version,
                    "enabled": True,
                },
                extra_audit_detail={"action": "enable"},
            )
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider identity or enabled type already exists",
        ) from error
    return JSONResponse(content=response_body, status_code=status.HTTP_200_OK)


@router.post("/{provider_id}/disable", response_model=ProviderConfigView)
async def disable_provider(
    provider_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> JSONResponse:
    """Disable a provider, releasing the per-type enabled slot.

    Distinct ``PROVIDER_CONFIG_DISABLED`` audit row. Idempotent under
    ``Idempotency-Key``. Disabling an already-disabled row still bumps the
    version and audits.
    """
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cached_response(begin_command(db, scope))
    if cached_response is not None:
        return cached_response
    master_key = _master_key()
    config = _scoped_config(db, tenant_id=admin.tenant_id, provider_id=provider_id)
    config.enabled = False
    config.version += 1
    trace_id = str(request.state.trace_id)
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        response_body = _finalize_provider_command(
            db=db,
            uow=uow,
            admin=admin,
            config=config,
            master_key=master_key,
            trace_id=trace_id,
            scope_key=scope.key,
            audit_action="PROVIDER_CONFIG_DISABLED",
            event_payload={
                "provider_type": config.provider_type.value,
                "version": config.version,
                "enabled": False,
            },
            extra_audit_detail={"action": "disable"},
        )
    return JSONResponse(content=response_body, status_code=status.HTTP_200_OK)


@router.delete("/{provider_id}", response_model=ProviderConfigView)
async def delete_provider(
    provider_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> JSONResponse:
    """Soft-delete a provider (``enabled=False``).

    BE-019: the row is preserved for audit and the ``provider_calls`` foreign-key
    history (``ondelete=SET NULL``). Hard-delete is intentionally refused. The
    ``DELETE`` is treated as a disable + a ``PROVIDER_CONFIG_DELETED`` audit row;
    the masked view is returned so the UI can update without a follow-up GET.
    Idempotent: replaying the same ``Idempotency-Key`` returns the cached body;
    deleting an already-disabled row with a fresh key is also safe.
    """
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cached_response(begin_command(db, scope))
    if cached_response is not None:
        return cached_response
    master_key = _master_key()
    config = _scoped_config(db, tenant_id=admin.tenant_id, provider_id=provider_id)
    config.enabled = False
    config.version += 1
    trace_id = str(request.state.trace_id)
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        response_body = _finalize_provider_command(
            db=db,
            uow=uow,
            admin=admin,
            config=config,
            master_key=master_key,
            trace_id=trace_id,
            scope_key=scope.key,
            audit_action="PROVIDER_CONFIG_DELETED",
            event_payload={
                "provider_type": config.provider_type.value,
                "version": config.version,
                "enabled": False,
                "soft_delete": True,
            },
            extra_audit_detail={"action": "soft_delete"},
        )
    return JSONResponse(content=response_body, status_code=status.HTTP_200_OK)
