"""身份领域仓储服务：封装用户、角色、会话的 DB 操作。

这是业务逻辑与持久化的边界。FastAPI 路由与 RBAC 依赖通过这些函数读写，
不直接操作 ORM 查询。所有写操作在调用方的事务内完成（调用方负责 commit）。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import RoleName, TenantType, TokenType, UserStatus
from app.models.identity import Role, Tenant, User, UserRole, UserSession


# --------------------------------------------------------------------------- #
# 角色与租户
# --------------------------------------------------------------------------- #
def get_role_by_name(db: Session, name: str) -> Role | None:
    """按名称查找角色。"""
    return db.scalar(select(Role).where(Role.name == name))


def ensure_role_exists(db: Session, name: str) -> Role:
    """获取角色，不存在则创建（用于种子/引导）。调用方负责 commit。"""
    role = get_role_by_name(db, name)
    if role is None:
        role = Role(name=name)
        db.add(role)
        db.flush()
    return role


def ensure_roles_seeded(db: Session) -> None:
    """确保五个系统角色存在（设计 §17.2）。调用方负责 commit。"""
    for name in RoleName:
        ensure_role_exists(db, name.value)


def get_or_create_tenant(
    db: Session, *, slug: str, name: str, tenant_type: TenantType = TenantType.STANDARD
) -> Tenant:
    """获取或创建租户。调用方负责 commit。"""
    tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant is None:
        tenant = Tenant(slug=slug, name=name, type=tenant_type)
        db.add(tenant)
        db.flush()
    return tenant


# --------------------------------------------------------------------------- #
# 用户
# --------------------------------------------------------------------------- #
def get_user_by_email(db: Session, *, tenant_id: UUID, email: str) -> User | None:
    """按租户+邮箱查找用户（租户隔离）。"""
    return db.scalar(select(User).where(User.tenant_id == tenant_id, User.email == email))


def get_user_by_id(db: Session, user_id: UUID) -> User | None:
    """按 ID 查找用户。"""
    return db.get(User, user_id)


def get_user_roles(db: Session, user_id: UUID) -> list[str]:
    """获取用户的角色名列表。"""
    rows = (
        db.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        .scalars()
        .all()
    )
    return list(rows)


def assign_role(db: Session, *, user_id: UUID, role_name: str) -> None:
    """给用户分配角色（幂等：已存在则跳过）。调用方负责 commit。"""
    role = ensure_role_exists(db, role_name)
    existing = db.scalar(
        select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id)
    )
    if existing is None:
        db.add(UserRole(user_id=user_id, role_id=role.id))
        db.flush()


def create_student_user(
    db: Session,
    *,
    tenant_id: UUID,
    email: str,
    password_hash: str,
    student_no: str | None = None,
    display_name: str | None = None,
) -> User:
    """创建 PENDING 状态的学生用户并分配 STUDENT 角色。调用方负责 commit。"""
    user = User(
        tenant_id=tenant_id,
        email=email,
        student_no=student_no,
        password_hash=password_hash,
        display_name=display_name,
        status=UserStatus.PENDING,
    )
    db.add(user)
    db.flush()
    assign_role(db, user_id=user.id, role_name=RoleName.STUDENT.value)
    return user


def set_user_status(db: Session, user: User, status: UserStatus) -> None:
    """更新用户状态（审核流转）。调用方负责 commit。"""
    user.status = status
    db.flush()


def list_pending_registrations(
    db: Session, *, tenant_id: UUID | None = None, limit: int = 50, offset: int = 0
) -> list[User]:
    """列出 PENDING 状态的用户（管理端审核列表）。"""
    stmt = select(User).where(User.status == UserStatus.PENDING)
    if tenant_id is not None:
        stmt = stmt.where(User.tenant_id == tenant_id)
    stmt = stmt.order_by(User.created_at.asc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def has_any_admin(db: Session) -> bool:
    """是否存在任意管理端角色用户（引导幂等判断用）。"""
    row = db.execute(
        select(UserRole.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            Role.name.in_(
                [
                    RoleName.SYSTEM_ADMIN.value,
                    RoleName.COURSE_ADMIN.value,
                    RoleName.REVIEWER.value,
                ]
            )
        )
        .limit(1)
    ).first()
    return row is not None


# --------------------------------------------------------------------------- #
# 会话（refresh token）
# --------------------------------------------------------------------------- #
def create_session(
    db: Session,
    *,
    user_id: UUID,
    jti: str,
    expires_at: datetime,
) -> UserSession:
    """创建刷新令牌会话。调用方负责 commit。"""
    session = UserSession(
        user_id=user_id,
        jti=jti,
        token_type=TokenType.REFRESH,
        expires_at=expires_at,
    )
    db.add(session)
    db.flush()
    return session


def get_session_by_jti(db: Session, jti: str) -> UserSession | None:
    """按 jti 查找会话。"""
    return db.scalar(select(UserSession).where(UserSession.jti == jti))


def revoke_session(db: Session, session: UserSession, now: datetime) -> None:
    """吊销会话（轮换/注销/复用检测）。调用方负责 commit。"""
    session.revoked = True
    session.revoked_at = now
    db.flush()
