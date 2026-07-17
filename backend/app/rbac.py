"""RBAC 依赖：从 JWT 解析当前用户、角色校验、租户隔离、管理端守卫。

所有受保护的路由通过这些依赖获取已认证用户。设计 §17.2：
- 学生只访问自己的画像、任务、证据和代码；
- 管理端权限最小化，路由独立守卫（学生令牌无法访问管理端）。
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models.base import RoleName, TokenType
from app.models.identity import User
from app.security import TokenError, decode_token
from app.services import get_user_by_id, get_user_roles

_settings = get_settings()

ADMIN_ROLES = {
    RoleName.COURSE_ADMIN.value,
    RoleName.REVIEWER.value,
    RoleName.SYSTEM_ADMIN.value,
}


def _extract_bearer_token(request: Request) -> str:
    """从 Authorization 头提取 Bearer token。"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid Authorization header",
        )
    return auth[len("Bearer ") :]


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """从 access token 解析当前用户。无 token/无效/过期 → 401。"""
    token = _extract_bearer_token(request)
    try:
        payload = decode_token(token, TokenType.ACCESS)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    try:
        user_id = UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token subject",
        ) from exc

    user = get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user not found",
        )
    return user


def require_roles(
    *allowed_roles: str,
) -> Callable[..., User]:
    """工厂依赖：要求当前用户持有任一指定角色，否则 403。"""

    def _dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        user_roles = set(get_user_roles(db, user.id))
        if not user_roles.intersection(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient role",
            )
        return user

    return _dependency


def require_admin(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    """管理端守卫：要求任一管理端角色（设计测试矩阵「管理端独立路由守卫」）。"""
    user_roles = set(get_user_roles(db, user.id))
    if not user_roles.intersection(ADMIN_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin role required",
        )
    return user


def require_tenant_match(resource_tenant_id: UUID, user: User) -> None:
    """租户隔离断言：用户只能访问自己租户的资源。违反 → 403。"""
    if user.tenant_id != resource_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tenant mismatch",
        )
