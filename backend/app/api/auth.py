"""认证路由：注册、登录、刷新、当前用户。

设计依据：
- §17.3.1 学生自助注册（PENDING）→ 管理员审核 → ACTIVE/REJECTED
- §17.3.3 JWT（短期）+ Refresh Token
- 测试矩阵：PENDING 登录拒绝、错误密码不泄漏账号存在性、token refresh/reuse

关键安全策略：
- PENDING/REJECTED/SUSPENDED 用户不能登录（FORBIDDEN）。
- 错误密码返回 AUTH_REQUIRED，不区分「用户不存在」与「密码错」（防枚举）。
- refresh token 一次性轮换：刷新时旧会话吊销 + 签发新会话；复用已吊销的
  refresh token 视为令牌被盗用（复用检测）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bootstrap import DEMO_GUEST_EMAIL, DEMO_TENANT_SLUG
from app.config import get_settings
from app.contracts.auth import (
    AuthTokens,
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenRefreshRequest,
    UserProfile,
)
from app.db import get_db
from app.models.base import RoleName, TenantType, TokenType, UserStatus
from app.models.identity import Tenant, User
from app.rbac import get_current_user
from app.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services import (
    create_session,
    create_student_user,
    get_or_create_tenant,
    get_session_by_jti,
    get_user_by_email,
    get_user_roles,
    revoke_session,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_settings = get_settings()


def _user_to_profile(user: User, roles: list[str]) -> UserProfile:
    """将 User ORM 对象转为不含敏感字段的 UserProfile 契约。"""
    return UserProfile(
        id=str(user.id),
        email=user.email,
        tenant_id=str(user.tenant_id),
        roles=roles,
        status=user.status.value,
        display_name=user.display_name,
    )


def _issue_token_pair(db: Session, user: User, roles: list[str]) -> AuthTokens:
    """签发 access + refresh token 对，并持久化 refresh 会话。"""
    access_token, _, _ = create_access_token(
        user_id=str(user.id), tenant_id=str(user.tenant_id), roles=roles
    )
    refresh_token, jti, expires_at = create_refresh_token(
        user_id=str(user.id), tenant_id=str(user.tenant_id), roles=roles
    )
    create_session(db, user_id=user.id, jti=jti, expires_at=expires_at)
    db.commit()
    return AuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=_settings.access_token_ttl_minutes * 60,
    )


# --------------------------------------------------------------------------- #
# 注册
# --------------------------------------------------------------------------- #
@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    """学生自助注册。注册即 PENDING，待管理员审核（设计 §17.3.1）。"""
    tenant = get_or_create_tenant(db, slug="default", name="Default Tenant")
    # 先检查是否已存在（友好错误），唯一约束兜底并发。
    existing = get_user_by_email(db, tenant_id=tenant.id, email=body.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email already registered in this tenant",
        )
    try:
        user = create_student_user(
            db,
            tenant_id=tenant.id,
            email=body.email,
            password_hash=hash_password(body.password),
            student_no=body.student_no,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email or student_no already registered",
        ) from exc

    return RegisterResponse(
        user_id=str(user.id),
        email=user.email,
        status="PENDING",
        message="Registration received. An administrator will review it.",
    )


# --------------------------------------------------------------------------- #
# 登录
# --------------------------------------------------------------------------- #
@router.post("/login", response_model=AuthTokens)
async def login(body: LoginRequest, db: Session = Depends(get_db)) -> AuthTokens:
    """学生/管理员登录。

    PENDING/REJECTED/SUSPENDED 用户不能登录（FORBIDDEN）。
    密码错误统一返回 401（不泄漏账号是否存在）。
    """
    # 登录用默认租户；多租户登录在后续任务细化。
    tenant = get_or_create_tenant(db, slug="default", name="Default Tenant")
    user = get_user_by_email(db, tenant_id=tenant.id, email=body.email)

    # 统一的失败路径：用户不存在或密码错误都返回 401（防枚举）。
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        )

    # 非 ACTIVE 用户不能登录。
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"account is {user.status.value.lower()}, cannot login",
        )

    roles = get_user_roles(db, user.id)
    return _issue_token_pair(db, user, roles)


@router.post("/demo", response_model=AuthTokens)
async def demo_login(db: Session = Depends(get_db)) -> AuthTokens:
    """Issue a session for the isolated, reset-safe demo guest."""

    tenant = db.scalar(
        select(Tenant).where(
            Tenant.slug == DEMO_TENANT_SLUG,
            Tenant.type == TenantType.DEMO,
        )
    )
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="demo environment unavailable",
        )
    guest = get_user_by_email(db, tenant_id=tenant.id, email=DEMO_GUEST_EMAIL)
    if guest is None or guest.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="demo environment unavailable",
        )
    roles = get_user_roles(db, guest.id)
    if set(roles) != {RoleName.DEMO_GUEST.value}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="demo environment unavailable",
        )
    return _issue_token_pair(db, guest, roles)


# --------------------------------------------------------------------------- #
# 刷新
# --------------------------------------------------------------------------- #
@router.post("/refresh", response_model=AuthTokens)
async def refresh(body: TokenRefreshRequest, db: Session = Depends(get_db)) -> AuthTokens:
    """用 refresh token 换新的 access + refresh token 对。

    一次性轮换：旧会话吊销，签发新会话。
    复用检测：已吊销的 refresh token 再次提交 → 401（令牌可能被盗用）。
    """
    try:
        payload = decode_token(body.refresh_token, TokenType.REFRESH)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid refresh token",
        ) from exc

    jti = str(payload.get("jti", ""))
    session = get_session_by_jti(db, jti)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh session not found",
        )
    # 复用检测：已吊销的会话被再次提交。
    if session.revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh token reuse detected",
        )

    # 吊销旧会话（轮换）。
    revoke_session(db, session, datetime.now(UTC))

    # 重新签发。
    from app.services import get_user_by_id

    user = get_user_by_id(db, session.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user no longer active",
        )
    roles = get_user_roles(db, user.id)
    return _issue_token_pair(db, user, roles)


# --------------------------------------------------------------------------- #
# 当前用户
# --------------------------------------------------------------------------- #
@router.get("/me", response_model=UserProfile)
async def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserProfile:
    """返回当前用户信息（不含密码哈希）。"""
    roles = get_user_roles(db, user.id)
    return _user_to_profile(user, roles)
