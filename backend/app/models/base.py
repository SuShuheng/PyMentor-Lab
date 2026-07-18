"""身份权限领域的枚举定义。

角色与状态遵循冻结设计 §17.2（角色）与 §17.3.1（注册审核流转）。
枚举值在契约层（packages/contracts）对齐，跨进程稳定，禁止改名。
"""

from __future__ import annotations

from enum import StrEnum


class RoleName(StrEnum):
    """系统角色（设计 §17.2）。枚举值是权限断言的稳定键。"""

    STUDENT = "STUDENT"
    DEMO_GUEST = "DEMO_GUEST"
    COURSE_ADMIN = "COURSE_ADMIN"
    REVIEWER = "REVIEWER"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"


class UserStatus(StrEnum):
    """用户生命周期状态（设计 §17.3.1 注册审核流转）。

    PENDING  — 已注册待管理员审核，不可登录。
    ACTIVE   — 审核通过，可登录。
    REJECTED — 审核拒绝，不可登录。
    SUSPENDED — 停用，不可登录。
    """

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class TenantType(StrEnum):
    """租户类型。演示租户可一键重置（设计 §17.3.1 游客）。"""

    STANDARD = "STANDARD"
    DEMO = "DEMO"


class TokenType(StrEnum):
    """JWT 类型标记，防止 access/refresh 混用。"""

    ACCESS = "ACCESS"
    REFRESH = "REFRESH"
