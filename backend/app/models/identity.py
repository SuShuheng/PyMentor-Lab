"""身份权限 ORM 模型（设计 §15.1 表分组「身份权限」）。

表：tenants, users, roles, user_roles, user_sessions。
字段规范遵循设计 §12.2：UUID 主键、created_at/updated_at、version（乐观锁）、
枚举状态统一、外键和唯一约束优先、JSONB 不替代关系模型。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import Uuid

from app.db import Base
from app.models.base import TenantType, TokenType, UserStatus


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid4)


class Tenant(Base):
    """租户。多租户隔离的顶层边界；演示租户支持一键重置。"""

    __tablename__ = "tenants"
    __table_args__ = (UniqueConstraint("slug", name="uq_tenants_slug"),)

    id: Mapped[UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[TenantType] = mapped_column(default=TenantType.STANDARD, nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    users: Mapped[list[User]] = relationship(back_populates="tenant")


class User(Base):
    """用户。学号/邮箱 + 密码哈希；注册即 PENDING，审核后 ACTIVE。

    password_hash 仅存 bcrypt 哈希，永不返回给任何调用方。
    tenant_id 是租户隔离的锚点；所有正式状态查询都按租户过滤。
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        UniqueConstraint("tenant_id", "student_no", name="uq_users_tenant_student_no"),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    student_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[UserStatus] = mapped_column(default=UserStatus.PENDING, nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tenant: Mapped[Tenant] = relationship(back_populates="users")
    roles: Mapped[list[UserRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Role(Base):
    """角色字典。种子数据在引导时创建（设计 §17.2 的五个角色）。"""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("name", name="uq_roles_name"),)

    id: Mapped[UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class UserRole(Base):
    """用户-角色关联。一个用户可持有多个角色（如 Course Admin + Reviewer）。"""

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),
    )

    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    granted_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship()


class UserSession(Base):
    """刷新令牌会话。jti 是唯一标识；revoked 支持轮换与复用检测。

    一次性轮换：刷新时旧 session 标记 revoked 并签发新 session。
    复用检测：已 revoked 的 session 再次被提交视为令牌被盗用（设计测试矩阵：
    token refresh/reuse）。
    """

    __tablename__ = "user_sessions"

    id: Mapped[UUID] = _uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    token_type: Mapped[TokenType] = mapped_column(default=TokenType.REFRESH, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked: Mapped[bool] = mapped_column(default=False, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")


def utc_now() -> datetime:
    """UTC 当前时间（测试与迁移复用）。"""
    return datetime.now(UTC)
