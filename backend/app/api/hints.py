"""Student hint request API (BE-005 Task 8).

``POST /api/v1/tasks/{task_instance_id}/hints`` records one ordered, budgeted
hint usage and returns the static hint content. The requested level must be the
next available level within the immutable budget, and the task version must
match. Replays return the original row via scoped idempotency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.command_idempotency import IdempotencyInProgressError, begin_command, scope_for_request
from app.contracts.sandbox import HintRequest, HintUsageView
from app.db import get_db
from app.hints import InvalidHintRequest, record_hint_usage
from app.idempotency import IdempotencyScopeConflictError, save_response
from app.models import TaskInstance, TaskInstanceStatus, User
from app.rbac import get_current_user
from app.uow import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/tasks", tags=["code-hints"])


def _now() -> datetime:
    return datetime.now(UTC)


@router.post("/{task_instance_id}/hints", response_model=HintUsageView)
async def request_hint(
    task_instance_id: str,
    body: HintRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    instance = db.scalar(
        select(TaskInstance).where(
            TaskInstance.id == task_instance_id,
            TaskInstance.tenant_id == user.tenant_id,
            TaskInstance.student_id == user.id,
        )
    )
    if instance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if instance.status != TaskInstanceStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"task is {instance.status.value.lower()}",
        )

    # Idempotency check BEFORE the version check: a replay must return the
    # original response even though the hint bumped the task version.
    scope = scope_for_request(request, tenant_id=user.tenant_id, user_id=user.id)
    try:
        cached = begin_command(db, scope)
    except IdempotencyScopeConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotency key scope conflict",
        ) from exc
    if cached is not None and cached.response_status is not None:
        return JSONResponse(
            content=cached.response_body or {},
            status_code=cached.response_status,
        )
    if cached is not None and cached.response_status is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotent command is still in progress",
        )
    # cached is None: a freshly created reservation; validate the version, then
    # record the hint.
    if instance.version != body.expected_task_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"expected task version {body.expected_task_version}, actual {instance.version}",
        )

    now = _now()
    try:
        with SqlAlchemyUnitOfWork(accept_session=db) as uow:
            usage = record_hint_usage(
                db,
                task=instance,
                level=body.level,
                revision_id=None,
                now=now,
            )
            db.flush()
            view = _hint_view(usage)
            # Complete the idempotent response in the same transaction as the hint
            # so a replay sees the committed response_status atomically.
            save_response(
                db,
                key=scope.key,
                response_status=status.HTTP_200_OK,
                response_body=view,
            )
            uow.commit()
    except InvalidHintRequest as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except IdempotencyInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotent command is still in progress",
        ) from exc

    return JSONResponse(content=view, status_code=status.HTTP_200_OK)


def _hint_view(usage: Any) -> dict[str, Any]:
    return {
        "id": str(usage.id),
        "task_instance_id": str(usage.task_instance_id),
        "revision_id": str(usage.revision_id) if usage.revision_id else None,
        "sequence": usage.sequence,
        "hint_key": usage.hint_key,
        "level": usage.level,
        "cost": usage.cost,
        "content": usage.content,
        "created_at": usage.created_at.isoformat(),
    }


__all__ = ["router"]
