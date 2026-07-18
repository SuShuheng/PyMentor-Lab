"""Tenant-scoped administrator registration review routes.

设计依据：
- §17.3.1 管理员审核 PENDING → ACTIVE/REJECTED
- §13.1 所有写 API 写审计上下文（trace_id）
- 设计 API 列表：POST /admin/tenants/{id}/reset

权限：所有 admin 路由要求管理端角色（require_admin 守卫）。
审计：操作记录通过 trace_id（中间件已注入）关联，BE-003 补正式审计表。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.command_idempotency import CommandScope, begin_command, scope_for_request
from app.contracts.auth import PendingRegistration, RegistrationDecisionRequest
from app.db import get_db
from app.evidence import record_audit
from app.idempotency import save_response
from app.models.base import UserStatus
from app.models.identity import User
from app.rbac import require_course_admin
from app.services import set_user_status
from app.uow import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# --------------------------------------------------------------------------- #
# 注册审核
# --------------------------------------------------------------------------- #
@router.get("/registrations/pending", response_model=list[PendingRegistration])
async def list_pending(
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[PendingRegistration]:
    """列出待审核注册（分页）。仅管理端可访问。"""
    stmt = (
        select(User)
        .where(User.status == UserStatus.PENDING, User.tenant_id == admin.tenant_id)
        .order_by(User.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    users = list(db.scalars(stmt))
    return [
        PendingRegistration(
            user_id=str(u.id),
            email=u.email,
            student_no=u.student_no,
            status=u.status.value,
            created_at=u.created_at.isoformat(),
        )
        for u in users
    ]


def _decide_registration(
    db: Session,
    user_id: UUID,
    new_status: UserStatus,
    *,
    action: str,
    admin: User,
    trace_id: str,
    scope: CommandScope,
) -> dict[str, str]:
    """审核决定的共享逻辑。"""
    user = db.scalar(
        select(User).where(User.id == user_id, User.tenant_id == admin.tenant_id)
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if user.status != UserStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"user is not PENDING (current: {user.status.value})",
        )
    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        set_user_status(db, user, new_status)
        response_body = {"user_id": str(user.id), "status": user.status.value}
        record_audit(
            db,
            tenant_id=user.tenant_id,
            actor_user_id=admin.id,
            action=action,
            resource_type="user",
            resource_id=str(user.id),
            trace_id=trace_id,
            detail={"new_status": new_status.value},
        )
        uow.publish(
            event_type=action,
            aggregate_type="user",
            aggregate_id=str(user.id),
            tenant_id=user.tenant_id,
            trace_id=trace_id,
            payload={"status": new_status.value},
        )
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_200_OK,
            response_body=response_body,
        )
        uow.commit()
    return response_body


def _cached(cached: object) -> JSONResponse | None:
    response_status = getattr(cached, "response_status", None)
    if cached is not None and response_status is not None:
        return JSONResponse(
            content=getattr(cached, "response_body", None) or {},
            status_code=response_status,
        )
    return None


@router.post("/registrations/{user_id}/approve", status_code=status.HTTP_200_OK)
async def approve_registration(
    user_id: UUID,
    _body: RegistrationDecisionRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
) -> JSONResponse:
    """批准注册：PENDING → ACTIVE。仅管理端可访问。"""
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cached(begin_command(db, scope))
    if cached_response is not None:
        return cached_response
    response_body = _decide_registration(
        db,
        user_id,
        UserStatus.ACTIVE,
        action="REGISTRATION_APPROVED",
        admin=admin,
        trace_id=str(request.state.trace_id),
        scope=scope,
    )
    return JSONResponse(response_body, status_code=status.HTTP_200_OK)


@router.post("/registrations/{user_id}/reject", status_code=status.HTTP_200_OK)
async def reject_registration(
    user_id: UUID,
    _body: RegistrationDecisionRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_course_admin),
) -> JSONResponse:
    """拒绝注册：PENDING → REJECTED。REJECTED 用户不能登录。仅管理端可访问。"""
    scope = scope_for_request(request, tenant_id=admin.tenant_id, user_id=admin.id)
    cached_response = _cached(begin_command(db, scope))
    if cached_response is not None:
        return cached_response
    response_body = _decide_registration(
        db,
        user_id,
        UserStatus.REJECTED,
        action="REGISTRATION_REJECTED",
        admin=admin,
        trace_id=str(request.state.trace_id),
        scope=scope,
    )
    return JSONResponse(response_body, status_code=status.HTTP_200_OK)
