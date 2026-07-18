"""密码哈希与 JWT 服务（纯函数，无 HTTP/DB 依赖）。

- 密码：bcrypt 哈希（业界标准、广泛审计）。hash 永不返回给调用方。
- JWT：access token（短期）+ refresh token（长期）。payload 含 sub、tenant_id、
  roles、type、jti、exp、iat。type 防止 access/refresh 混用。

token 时长可由环境变量覆盖（设计 §17.3.3：JWT 短期 + Refresh Token）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.config import get_settings
from app.models.base import RoleName, TokenType

_settings = get_settings()

# bcrypt 限制密码最长 72 字节；我们在哈希前做长度校验（明确拒绝而非静默截断）。
_MAX_PASSWORD_BYTES = 72


# --------------------------------------------------------------------------- #
# 密码哈希（直接用 bcrypt 库，不经过 passlib，避免 4.x 兼容问题）
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """返回 bcrypt 哈希（utf-8 编码）。永不存储/返回明文密码。"""
    _validate_password_length(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """恒定时间校验密码与哈希是否匹配。"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def _validate_password_length(password: str) -> None:
    """bcrypt 上限 72 字节；超出则拒绝（明确而非静默截断）。"""
    if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        raise ValueError("password too long (max 72 bytes)")


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def _create_token(
    *,
    user_id: str,
    tenant_id: str,
    roles: list[str],
    token_type: TokenType,
    ttl: timedelta,
) -> tuple[str, str, datetime]:
    """签发 JWT。返回 (token, jti, expires_at)。"""
    now = datetime.now(UTC)
    jti = uuid.uuid4().hex
    expires_at = now + ttl
    payload: dict[str, Any] = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "type": token_type.value,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)
    return token, jti, expires_at


def create_access_token(
    *, user_id: str, tenant_id: str, roles: list[str]
) -> tuple[str, str, datetime]:
    """签发短期 access token。返回 (token, jti, expires_at)。"""
    return _create_token(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=roles,
        token_type=TokenType.ACCESS,
        ttl=timedelta(minutes=_settings.access_token_ttl_minutes),
    )


def create_refresh_token(
    *, user_id: str, tenant_id: str, roles: list[str]
) -> tuple[str, str, datetime]:
    """签发长期 refresh token。返回 (token, jti, expires_at)。"""
    return _create_token(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=roles,
        token_type=TokenType.REFRESH,
        ttl=timedelta(days=_settings.refresh_token_ttl_days),
    )


class TokenError(Exception):
    """令牌无效/过期/类型不符。调用方映射到 AUTH_REQUIRED。"""


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """校验并解码 JWT。失败抛 TokenError。

    - 签名无效 / 过期 / 格式错 → TokenError
    - type 不匹配（access 当 refresh 用） → TokenError
    """
    try:
        payload = jwt.decode(token, _settings.jwt_secret, algorithms=[_settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError("invalid or expired token") from exc

    if payload.get("type") != expected_type.value:
        raise TokenError(f"expected {expected_type.value} token")
    return payload


def user_roles_payload(roles: list[str]) -> list[str]:
    """规范化角色列表（供 payload 与 RBAC 一致使用）。"""
    return [r for r in roles if r]


def is_admin_role(role: str) -> bool:
    """是否为任一管理端角色（设计 §17.2 管理端守卫）。"""
    return role in {
        RoleName.COURSE_ADMIN.value,
        RoleName.REVIEWER.value,
        RoleName.SYSTEM_ADMIN.value,
    }
