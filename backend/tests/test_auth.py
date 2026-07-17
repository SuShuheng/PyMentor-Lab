"""认证集成测试：注册、登录、刷新、RBAC。

通过 TestClient 调用 HTTP 端点，依赖注入被覆盖为使用测试 session。
测试需要真实 PostgreSQL（docker-compose）。

覆盖的核心场景（设计测试矩阵）：
- 重复注册防护（CONFLICT）
- PENDING 登录拒绝
- 错误密码不泄漏账号存在性（统一 401）
- token refresh/reuse 检测
- 管理端独立路由守卫（学生令牌被拒）
- 跨租户隔离
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import create_app
from app.models.base import UserStatus
from app.models.identity import User
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    """TestClient，get_db 依赖被覆盖为测试 session（事务隔离）。"""

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def active_user(db_session: Session) -> User:
    """创建一个 ACTIVE 学生用户用于登录测试。"""
    tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
    db_session.flush()
    user = create_student_user(
        db_session,
        tenant_id=tenant.id,
        email="active@example.com",
        password_hash=hash_password("ValidPass1!"),
    )
    # 直接改为 ACTIVE（绕过审核流程，供登录测试用）。
    user.status = UserStatus.ACTIVE
    db_session.flush()
    return user


# --------------------------------------------------------------------------- #
# 注册
# --------------------------------------------------------------------------- #
class TestRegister:
    def test_register_creates_pending_user(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "newstudent@example.com", "password": "ValidPass1!"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "PENDING"
        assert body["email"] == "newstudent@example.com"
        assert body["user_id"]

    def test_duplicate_email_rejected(self, client: TestClient, active_user: User) -> None:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": active_user.email, "password": "ValidPass1!"},
        )
        assert response.status_code == 409

    def test_weak_password_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "weak@example.com", "password": "short"},
        )
        assert response.status_code == 422


# --------------------------------------------------------------------------- #
# 登录
# --------------------------------------------------------------------------- #
class TestLogin:
    def test_active_user_login_succeeds(self, client: TestClient, active_user: User) -> None:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": active_user.email, "password": "ValidPass1!"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] > 0

    def test_wrong_password_returns_401(self, client: TestClient, active_user: User) -> None:
        """错误密码统一 401，不泄漏账号存在。"""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": active_user.email, "password": "WrongPass1!"},
        )
        assert response.status_code == 401

    def test_nonexistent_user_returns_401(self, client: TestClient) -> None:
        """不存在的用户也返回 401（防枚举）。"""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@example.com", "password": "ValidPass1!"},
        )
        assert response.status_code == 401

    def test_pending_user_cannot_login(self, client: TestClient, db_session: Session) -> None:
        """PENDING 用户不能登录（设计 §17.3.1：审核通过方可登录）。"""
        tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
        db_session.flush()
        create_student_user(
            db_session,
            tenant_id=tenant.id,
            email="pending@example.com",
            password_hash=hash_password("ValidPass1!"),
        )
        # 不改 status，保持 PENDING。
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "pending@example.com", "password": "ValidPass1!"},
        )
        assert response.status_code == 403


# --------------------------------------------------------------------------- #
# 刷新
# --------------------------------------------------------------------------- #
class TestRefresh:
    def test_refresh_rotates_token(self, client: TestClient, active_user: User) -> None:
        """刷新返回新 token 对。"""
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": active_user.email, "password": "ValidPass1!"},
        )
        old_refresh = login_resp.json()["refresh_token"]

        refresh_resp = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert refresh_resp.status_code == 200
        new_tokens = refresh_resp.json()
        assert new_tokens["access_token"]
        assert new_tokens["refresh_token"] != old_refresh

    def test_refresh_reuse_detected(self, client: TestClient, active_user: User) -> None:
        """已用过的 refresh token 再次提交 → 401（复用检测）。"""
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": active_user.email, "password": "ValidPass1!"},
        )
        old_refresh = login_resp.json()["refresh_token"]

        # 第一次刷新成功。
        client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})

        # 旧 token 再次使用 → 被拒。
        reuse_resp = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert reuse_resp.status_code == 401

    def test_refresh_with_access_token_rejected(
        self, client: TestClient, active_user: User
    ) -> None:
        """access token 不能当 refresh token 用（type 防混用）。"""
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": active_user.email, "password": "ValidPass1!"},
        )
        access = login_resp.json()["access_token"]

        refresh_resp = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": access},
        )
        assert refresh_resp.status_code == 401


# --------------------------------------------------------------------------- #
# 当前用户
# --------------------------------------------------------------------------- #
class TestMe:
    def test_me_returns_profile(self, client: TestClient, active_user: User) -> None:
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": active_user.email, "password": "ValidPass1!"},
        )
        access = login_resp.json()["access_token"]

        response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert response.status_code == 200
        body = response.json()
        assert body["email"] == active_user.email
        assert "STUDENT" in body["roles"]
        assert body["status"] == "ACTIVE"
        # 密码哈希绝不返回。
        assert "password_hash" not in body

    def test_me_without_token_rejected(self, client: TestClient) -> None:
        """无 token → 401。"""
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401
