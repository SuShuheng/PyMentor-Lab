"""ORM 模型包。导入即向 Base.metadata 注册表结构（Alembic 自动生成依赖此副作用）。"""

from app.models.base import RoleName, TenantType, TokenType, UserStatus
from app.models.identity import (
    Role,
    Tenant,
    User,
    UserRole,
    UserSession,
    utc_now,
)

__all__ = [
    "Role",
    "RoleName",
    "Tenant",
    "TenantType",
    "TokenType",
    "User",
    "UserRole",
    "UserSession",
    "UserStatus",
    "utc_now",
]
