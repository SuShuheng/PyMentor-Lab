"""认证契约（Pydantic 镜像）。

Mirror of ``packages/contracts/src/auth.ts``。字段名与形态必须与 Zod 侧字节级一致；
conformance gate（``backend/tests/test_contracts_parity.py``）强制校验。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AuthTokenType(StrEnum):
    """令牌类型枚举（wire 上用字符串值）。"""

    BEARER = "Bearer"


class RegisterRequest(BaseModel):
    """学生自助注册请求（设计 §17.3.1）。注册即 PENDING。"""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    student_no: str | None = Field(default=None, max_length=64)


class RegisterResponse(BaseModel):
    """注册成功响应。status 恒为 PENDING，待管理员审核。"""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)
    email: EmailStr
    status: Literal["PENDING"] = "PENDING"
    message: str = Field(min_length=1)


class LoginRequest(BaseModel):
    """登录请求（学生/管理员通用）。"""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1)


class AuthTokens(BaseModel):
    """令牌对。access_token 短期，refresh_token 长期（设计 §17.3.3）。"""

    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(min_length=1)
    refresh_token: str = Field(min_length=1)
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int = Field(ge=1, description="access token 有效期（秒）")


class TokenRefreshRequest(BaseModel):
    """刷新令牌请求。"""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1)


class UserProfile(BaseModel):
    """当前用户信息（GET /auth/me）。不含密码哈希。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    email: EmailStr
    tenant_id: str = Field(min_length=1)
    roles: list[str] = Field(default_factory=list)
    status: str = Field(min_length=1)
    display_name: str | None = None


class PendingRegistration(BaseModel):
    """待审核注册条目（管理端列表用）。"""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)
    email: EmailStr
    student_no: str | None = None
    status: str = Field(min_length=1)
    created_at: str = Field(min_length=1)


class RegistrationDecisionRequest(BaseModel):
    """管理员审核决定（批准/拒绝）。"""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)
