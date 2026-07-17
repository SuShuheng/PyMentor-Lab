"""管理员路由：注册审核、demo 租户重置。

设计依据：
- §17.3.1 管理员审核 PENDING → ACTIVE/REJECTED
- §13.1 所有写 API 写审计上下文（trace_id）
- 设计 API 列表：POST /admin/tenants/{id}/reset

权限：所有 admin 路由要求管理端角色（require_admin 守卫）。
审计：操作记录通过 trace_id（中间件已注入）关联，BE-003 补正式审计表。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.auth import PendingRegistration, RegistrationDecisionRequest
from app.db import get_db
from app.models.base import RoleName, TenantType, UserStatus
from app.models.identity import Tenant, User
from app.rbac import require_admin
from app.services import get_user_by_id, set_user_status

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# --------------------------------------------------------------------------- #
# 注册审核
# --------------------------------------------------------------------------- #
@router.get("/registrations/pending", response_model=list[PendingRegistration])
async def list_pending(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
    limit: int = 50,
    offset: int = 0,
) -> list[PendingRegistration]:
    """列出待审核注册（分页）。仅管理端可访问。"""
    stmt = (
        select(User)
        .where(User.status == UserStatus.PENDING)
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
    db: Session, user_id: UUID, new_status: UserStatus, error_detail: str
) -> User:
    """审核决定的共享逻辑。"""
    user = get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if user.status != UserStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"user is not PENDING (current: {user.status.value})",
        )
    set_user_status(db, user, new_status)
    db.commit()
    return user


@router.post("/registrations/{user_id}/approve", status_code=status.HTTP_200_OK)
async def approve_registration(
    user_id: UUID,
    _body: RegistrationDecisionRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict[str, str]:
    """批准注册：PENDING → ACTIVE。仅管理端可访问。"""
    user = _decide_registration(db, user_id, UserStatus.ACTIVE, "approve")
    return {"user_id": str(user.id), "status": user.status.value}


@router.post("/registrations/{user_id}/reject", status_code=status.HTTP_200_OK)
async def reject_registration(
    user_id: UUID,
    _body: RegistrationDecisionRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict[str, str]:
    """拒绝注册：PENDING → REJECTED。REJECTED 用户不能登录。仅管理端可访问。"""
    user = _decide_registration(db, user_id, UserStatus.REJECTED, "reject")
    return {"user_id": str(user.id), "status": user.status.value}


# --------------------------------------------------------------------------- #
# demo 租户重置
# --------------------------------------------------------------------------- #
@router.post("/tenants/{tenant_id}/reset", status_code=status.HTTP_200_OK)
async def reset_demo_tenant(
    tenant_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, str]:
    """重置 demo 租户数据。

    仅 System Admin 可执行（设计 API 列表）。
    关键约束：只清除指定 demo 租户的数据，不影响其他租户（设计验收）。
    """
    # 权限细粒度：租户重置仅 System Admin。
    from app.services import get_user_roles

    admin_roles = set(get_user_roles(db, admin.id))
    if RoleName.SYSTEM_ADMIN.value not in admin_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="system admin role required for tenant reset",
        )

    # 确认目标租户存在且为 DEMO 类型。
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    if tenant.type != TenantType.DEMO:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only demo tenants can be reset",
        )

    # 删除该租户下的所有用户（级联删除 user_roles/user_sessions）。
    # 正式状态表（evidence/profiles 等）在 BE-003 加入后也按 tenant_id 过滤清除。
    users_to_delete = list(
        db.scalars(select(User).where(User.tenant_id == tenant_id))
    )
    for u in users_to_delete:
        db.delete(u)
    db.commit()

    return {
        "tenant_id": str(tenant_id),
        "reset": "completed",
        "users_removed": str(len(users_to_delete)),
    }
