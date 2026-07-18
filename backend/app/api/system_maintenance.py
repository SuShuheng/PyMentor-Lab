"""System Admin-only database, reset, and privacy maintenance commands."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.command_idempotency import CommandScope, begin_command, scope_for_request
from app.contracts.errors import ErrorCode, ErrorEnvelope
from app.contracts.maintenance import (
    DatabaseBackupView,
    DatabaseRestoreRequest,
    DatabaseStatusView,
    DatabaseTableUsage,
    DemoResetView,
    MaintenanceConfirmationRequest,
    MaintenanceOperationView,
    StudentDeleteView,
)
from app.db import get_db
from app.evidence import record_audit
from app.idempotency import save_response
from app.maintenance import DatabaseMaintenance, build_database_maintenance
from app.models import DatabaseBackup, IdempotencyKey, MaintenanceOperation, Tenant, User
from app.models.base import RoleName, TenantType
from app.rbac import require_system_admin
from app.services import get_user_roles
from app.uow import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/admin", tags=["admin-maintenance"])


def get_database_maintenance() -> DatabaseMaintenance:
    return build_database_maintenance()


def _confirm(actual: str, expected: str) -> None:
    if actual != expected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="exact maintenance confirmation required",
        )


def _cached(cached: object) -> JSONResponse | None:
    response_status = getattr(cached, "response_status", None)
    if cached is not None and response_status is not None:
        return JSONResponse(
            content=getattr(cached, "response_body", None) or {},
            status_code=response_status,
        )
    return None


def _backup_view(backup: DatabaseBackup) -> DatabaseBackupView:
    return DatabaseBackupView(
        id=backup.id,
        status=backup.status,
        content_digest=backup.digest,
        size_bytes=backup.size_bytes,
        created_at=backup.created_at,
    )


def _operation_view(operation: MaintenanceOperation) -> MaintenanceOperationView:
    return MaintenanceOperationView(
        id=operation.id,
        operation=operation.operation_type,
        status=operation.status,
        backup_id=operation.backup_id,
        error_code=operation.error_code,
        requested_at=operation.created_at,
        completed_at=operation.completed_at,
    )


def _maintenance_error_body(*, trace_id: str, message: str) -> dict[str, Any]:
    return ErrorEnvelope(
        code=ErrorCode.INTERNAL_ERROR,
        message=message,
        trace_id=trace_id,
        retryable=False,
    ).model_dump(mode="json")


@router.get("/system/db", response_model=DatabaseStatusView)
async def database_status(
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> DatabaseStatusView:
    revision = db.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    database_size = db.scalar(text("SELECT pg_database_size(current_database())"))
    active_connections = db.scalar(
        text(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() AND state <> 'idle'"
        )
    )
    slow_queries = db.scalar(
        text(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() AND state <> 'idle' "
            "AND pid <> pg_backend_pid() "
            "AND query_start < clock_timestamp() - interval '5 seconds'"
        )
    )
    table_count = db.scalar(
        text(
            "SELECT count(*) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r'"
        )
    )
    rows = db.execute(
        text(
            "SELECT c.relname AS name, pg_total_relation_size(c.oid) AS size_bytes, "
            "GREATEST(c.reltuples::bigint, 0) AS estimated_rows "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' "
            "ORDER BY size_bytes DESC, name ASC LIMIT 100"
        )
    ).mappings()
    tables = [
        DatabaseTableUsage(
            name=str(row["name"]),
            size_bytes=int(row["size_bytes"]),
            estimated_rows=int(row["estimated_rows"]),
        )
        for row in rows
    ]
    last_backup = db.scalar(
        select(DatabaseBackup)
        .where(
            DatabaseBackup.tenant_id == admin.tenant_id,
            DatabaseBackup.status == "AVAILABLE",
        )
        .order_by(DatabaseBackup.created_at.desc(), DatabaseBackup.id.desc())
        .limit(1)
    )
    return DatabaseStatusView(
        connected=True,
        engine="PostgreSQL",
        schema_revision=str(revision or "unknown"),
        database_size_bytes=int(database_size or 0),
        active_connections=int(active_connections or 0),
        slow_query_count=int(slow_queries or 0),
        table_count=int(table_count or 0),
        tables=tables,
        last_backup=None if last_backup is None else _backup_view(last_backup),
    )


@router.post(
    "/system/db/backup",
    response_model=DatabaseBackupView,
    status_code=status.HTTP_201_CREATED,
)
async def create_database_backup(
    body: MaintenanceConfirmationRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
    maintenance: DatabaseMaintenance = Depends(get_database_maintenance),
) -> JSONResponse:
    _confirm(body.confirmation, "BACKUP DATABASE")
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cached(begin_command(db, scope))
    if cached_response is not None:
        return cached_response
    backup_id = uuid4()
    trace_id = str(request.state.trace_id)
    try:
        artifact = await run_in_threadpool(maintenance.create_backup, backup_id)
    except Exception:
        response_body = _maintenance_error_body(
            trace_id=trace_id,
            message="Database backup failed.",
        )
        _record_failed_operation(
            db,
            scope=scope,
            admin=admin,
            trace_id=trace_id,
            operation_type="DATABASE_BACKUP",
            action="DATABASE_BACKUP_FAILED",
            backup_id=None,
            error_code="BACKUP_FAILED",
            response_body=response_body,
        )
        return JSONResponse(response_body, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    completed_at = datetime.now(UTC)
    backup = DatabaseBackup(
        id=backup_id,
        tenant_id=admin.tenant_id,
        object_key=artifact.object_key,
        digest=artifact.digest,
        size_bytes=artifact.size_bytes,
        status="AVAILABLE",
        created_by=admin.id,
    )
    operation = MaintenanceOperation(
        tenant_id=admin.tenant_id,
        operation_type="DATABASE_BACKUP",
        status="SUCCEEDED",
        backup_id=backup_id,
        requested_by=admin.id,
        trace_id=trace_id,
        completed_at=completed_at,
    )
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        db.add_all([backup, operation])
        db.flush()
        response_body = _backup_view(backup).model_dump(mode="json")
        record_audit(
            db,
            tenant_id=admin.tenant_id,
            actor_user_id=admin.id,
            action="DATABASE_BACKUP_CREATED",
            resource_type="database_backup",
            resource_id=str(backup.id),
            trace_id=trace_id,
            detail={
                "confirmation_verified": True,
                "content_digest": backup.digest,
                "size_bytes": backup.size_bytes,
            },
        )
        uow.publish(
            event_type="DATABASE_BACKUP_CREATED",
            aggregate_type="database_backup",
            aggregate_id=str(backup.id),
            tenant_id=admin.tenant_id,
            trace_id=trace_id,
            payload={"content_digest": backup.digest, "size_bytes": backup.size_bytes},
        )
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_201_CREATED,
            response_body=response_body,
        )
        uow.commit()
    return JSONResponse(response_body, status_code=status.HTTP_201_CREATED)


def _record_failed_operation(
    db: Session,
    *,
    scope: CommandScope,
    admin: User,
    trace_id: str,
    operation_type: str,
    action: str,
    backup_id: UUID | None,
    error_code: str,
    response_body: dict[str, Any],
) -> MaintenanceOperation:
    operation = MaintenanceOperation(
        tenant_id=admin.tenant_id,
        operation_type=operation_type,
        status="FAILED",
        backup_id=backup_id,
        requested_by=admin.id,
        error_code=error_code,
        trace_id=trace_id,
        completed_at=datetime.now(UTC),
    )
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        db.add(operation)
        db.flush()
        detail: dict[str, str | bool] = {
            "confirmation_verified": True,
            "error_code": error_code,
        }
        if backup_id is not None:
            detail["backup_id"] = str(backup_id)
        record_audit(
            db,
            tenant_id=admin.tenant_id,
            actor_user_id=admin.id,
            action=action,
            resource_type="maintenance_operation",
            resource_id=str(operation.id),
            trace_id=trace_id,
            detail=detail,
        )
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            response_body=response_body,
        )
        uow.commit()
    return operation


@router.post("/system/db/restore", response_model=MaintenanceOperationView)
async def restore_database_backup(
    body: DatabaseRestoreRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
    maintenance: DatabaseMaintenance = Depends(get_database_maintenance),
) -> JSONResponse:
    _confirm(body.confirmation, "RESTORE DATABASE")
    backup = db.scalar(
        select(DatabaseBackup).where(
            DatabaseBackup.id == body.backup_id,
            DatabaseBackup.tenant_id == admin.tenant_id,
            DatabaseBackup.status == "AVAILABLE",
        )
    )
    if backup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cached(begin_command(db, scope))
    if cached_response is not None:
        return cached_response
    trace_id = str(request.state.trace_id)
    object_key = backup.object_key
    digest = backup.digest
    backup_id = backup.id
    backup_size = backup.size_bytes
    backup_created_at = backup.created_at
    admin_id = admin.id
    tenant_id = admin.tenant_id
    # Release all request-transaction locks before pg_restore opens its own
    # connection. A failed --single-transaction restore leaves current data intact.
    if getattr(maintenance, "requires_released_transaction", False):
        db.commit()
    try:
        await run_in_threadpool(
            partial(
                maintenance.restore_backup,
                object_key=object_key,
                expected_digest=digest,
            )
        )
    except Exception:
        response_body = _maintenance_error_body(
            trace_id=trace_id,
            message="Database restore failed.",
        )
        _record_failed_operation(
            db,
            scope=scope,
            admin=admin,
            trace_id=trace_id,
            operation_type="DATABASE_RESTORE",
            action="DATABASE_RESTORE_FAILED",
            backup_id=backup_id,
            error_code="RESTORE_FAILED",
            response_body=response_body,
        )
        return JSONResponse(response_body, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    db.expire_all()
    actor_exists = db.get(User, admin_id) is not None
    restored_backup = db.get(DatabaseBackup, backup_id)
    if restored_backup is None:
        restored_backup = DatabaseBackup(
            id=backup_id,
            tenant_id=tenant_id,
            object_key=object_key,
            digest=digest,
            size_bytes=backup_size,
            status="AVAILABLE",
            created_by=admin_id if actor_exists else None,
            created_at=backup_created_at,
        )
        db.add(restored_backup)
        db.flush()
    stale_reservation = db.scalar(select(IdempotencyKey).where(IdempotencyKey.key == scope.key))
    if stale_reservation is not None:
        db.delete(stale_reservation)
        db.flush()
    db.add(
        IdempotencyKey(
            key=scope.key,
            tenant_id=tenant_id,
            user_id=admin_id if actor_exists else None,
            endpoint=scope.endpoint,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
    )
    db.flush()
    operation = MaintenanceOperation(
        tenant_id=tenant_id,
        operation_type="DATABASE_RESTORE",
        status="SUCCEEDED",
        backup_id=backup_id,
        requested_by=admin_id if actor_exists else None,
        trace_id=trace_id,
        completed_at=datetime.now(UTC),
    )
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        db.add(operation)
        db.flush()
        response_body = _operation_view(operation).model_dump(mode="json")
        record_audit(
            db,
            tenant_id=tenant_id,
            actor_user_id=admin_id if actor_exists else None,
            action="DATABASE_RESTORED",
            resource_type="database_backup",
            resource_id=str(backup_id),
            trace_id=trace_id,
            detail={"backup_id": str(backup_id), "confirmation_verified": True},
        )
        uow.publish(
            event_type="DATABASE_RESTORED",
            aggregate_type="database_backup",
            aggregate_id=str(backup_id),
            tenant_id=tenant_id,
            trace_id=trace_id,
            payload={"backup_id": str(backup_id)},
        )
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_200_OK,
            response_body=response_body,
        )
        uow.commit()
    return JSONResponse(response_body, status_code=status.HTTP_200_OK)


@router.delete("/students/{student_id}", response_model=StudentDeleteView)
async def delete_student_data(
    student_id: UUID,
    body: MaintenanceConfirmationRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> JSONResponse:
    _confirm(body.confirmation, f"DELETE STUDENT {student_id}")
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cached(begin_command(db, scope))
    if cached_response is not None:
        return cached_response
    student = db.scalar(
        select(User).where(User.id == student_id, User.tenant_id == admin.tenant_id)
    )
    if student is None or RoleName.STUDENT.value not in set(get_user_roles(db, student.id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    if student.id == admin.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Self deletion denied")
    trace_id = str(request.state.trace_id)
    operation = MaintenanceOperation(
        tenant_id=admin.tenant_id,
        operation_type="STUDENT_DELETE",
        status="SUCCEEDED",
        requested_by=admin.id,
        trace_id=trace_id,
        completed_at=datetime.now(UTC),
    )
    response_body = StudentDeleteView(student_id=student.id, deleted=True).model_dump(mode="json")
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        db.add(operation)
        record_audit(
            db,
            tenant_id=admin.tenant_id,
            actor_user_id=admin.id,
            action="STUDENT_DATA_DELETED",
            resource_type="user",
            resource_id=str(student.id),
            trace_id=trace_id,
            detail={"confirmation_verified": True},
        )
        uow.publish(
            event_type="STUDENT_DATA_DELETED",
            aggregate_type="user",
            aggregate_id=str(student.id),
            tenant_id=admin.tenant_id,
            trace_id=trace_id,
            payload={},
        )
        db.delete(student)
        db.flush()
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_200_OK,
            response_body=response_body,
        )
        uow.commit()
    return JSONResponse(response_body, status_code=status.HTTP_200_OK)


@router.post("/tenants/{tenant_id}/reset", response_model=DemoResetView)
async def reset_demo_tenant(
    tenant_id: UUID,
    body: MaintenanceConfirmationRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_system_admin),
) -> JSONResponse:
    _confirm(body.confirmation, f"RESET DEMO TENANT {tenant_id}")
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    if tenant.type != TenantType.DEMO:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only demo tenants reset")
    if tenant.id == admin.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot reset the operator tenant",
        )
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cached(begin_command(db, scope))
    if cached_response is not None:
        return cached_response
    users = list(db.scalars(select(User).where(User.tenant_id == tenant_id)))
    trace_id = str(request.state.trace_id)
    operation = MaintenanceOperation(
        tenant_id=tenant_id,
        operation_type="DEMO_TENANT_RESET",
        status="SUCCEEDED",
        requested_by=admin.id,
        trace_id=trace_id,
        completed_at=datetime.now(UTC),
    )
    response_body = DemoResetView(
        tenant_id=tenant_id,
        reset="completed",
        users_removed=len(users),
    ).model_dump(mode="json")
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        db.add(operation)
        for user in users:
            db.delete(user)
        db.flush()
        record_audit(
            db,
            tenant_id=tenant_id,
            actor_user_id=admin.id,
            action="DEMO_TENANT_RESET",
            resource_type="tenant",
            resource_id=str(tenant_id),
            trace_id=trace_id,
            detail={"confirmation_verified": True, "users_removed": len(users)},
        )
        uow.publish(
            event_type="DEMO_TENANT_RESET",
            aggregate_type="tenant",
            aggregate_id=str(tenant_id),
            tenant_id=tenant_id,
            trace_id=trace_id,
            payload={"users_removed": len(users)},
        )
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_200_OK,
            response_body=response_body,
        )
        uow.commit()
    return JSONResponse(response_body, status_code=status.HTTP_200_OK)
