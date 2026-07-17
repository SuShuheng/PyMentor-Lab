"""security 服务测试：密码哈希往返、JWT 签发/解码/拒绝。纯函数，不依赖 PG。"""

from __future__ import annotations

import time

import pytest

from app.models.base import TokenType
from app.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    is_admin_role,
    verify_password,
)

USER_ID = "00000000-0000-0000-0000-000000000001"
TENANT_ID = "00000000-0000-0000-0000-000000000002"
ROLES = ["STUDENT"]


# --------------------------------------------------------------------------- #
# 密码哈希
# --------------------------------------------------------------------------- #
class TestPasswordHashing:
    def test_hash_and_verify_round_trip(self) -> None:
        password = "S3cret-Pass!"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed)

    def test_wrong_password_rejected(self) -> None:
        hashed = hash_password("correct-password")
        assert not verify_password("wrong-password", hashed)

    def test_hash_is_bcrypt_format(self) -> None:
        hashed = hash_password("any-password")
        # bcrypt 哈希以 $2 开头。
        assert hashed.startswith("$2")


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
class TestJwtTokens:
    def test_access_token_round_trip(self) -> None:
        token, jti, expires_at = create_access_token(
            user_id=USER_ID, tenant_id=TENANT_ID, roles=ROLES
        )
        assert jti
        assert expires_at
        payload = decode_token(token, TokenType.ACCESS)
        assert payload["sub"] == USER_ID
        assert payload["tenant_id"] == TENANT_ID
        assert payload["roles"] == ROLES
        assert payload["type"] == "ACCESS"

    def test_refresh_token_round_trip(self) -> None:
        token, jti, _ = create_refresh_token(
            user_id=USER_ID, tenant_id=TENANT_ID, roles=ROLES
        )
        payload = decode_token(token, TokenType.REFRESH)
        assert payload["type"] == "REFRESH"
        assert payload["jti"] == jti

    def test_access_token_rejected_as_refresh(self) -> None:
        """type 防混用：access 不能当 refresh 用。"""
        token, _, _ = create_access_token(user_id=USER_ID, tenant_id=TENANT_ID, roles=ROLES)
        with pytest.raises(TokenError):
            decode_token(token, TokenType.REFRESH)

    def test_garbage_token_rejected(self) -> None:
        with pytest.raises(TokenError):
            decode_token("not.a.real.token", TokenType.ACCESS)

    def test_wrong_secret_rejected(self) -> None:
        """用错误密钥签的 token 被拒。"""
        import jwt as pyjwt

        from app.config import get_settings

        settings = get_settings()
        # 用足够长（>=32 字节）的错误密钥，避免触发密钥长度警告。
        bad_token = pyjwt.encode(
            {"sub": USER_ID, "type": "ACCESS", "exp": int(time.time()) + 60},
            "this-is-a-wrong-secret-but-long-enough-32bytes",
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(TokenError):
            decode_token(bad_token, TokenType.ACCESS)


def test_is_admin_role() -> None:
    assert is_admin_role("COURSE_ADMIN")
    assert is_admin_role("SYSTEM_ADMIN")
    assert not is_admin_role("STUDENT")
    assert not is_admin_role("DEMO_GUEST")
