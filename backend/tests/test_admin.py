"""管理员审核、bootstrap 引导、demo 租户重置测试。

覆盖 Slice 9-11（设计测试矩阵）：
- 管理端独立路由守卫（学生令牌被拒）
- PENDING→ACTIVE/REJECTED 审核流转
- REJECTED 用户不能登录
- bootstrap 幂等（重复执行无副作用）
- demo 租户重置不影响其他租户
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import create_app
from app.models.base import RoleName, TenantType, UserStatus
from app.models.consistency import AuditEvent, OutboxEvent
from app.models.identity import Tenant, User
from app.security import hash_password
from app.services import (
    assign_role,
    create_student_user,
    get_or_create_tenant,
    get_user_by_email,
    get_user_roles,
)


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client: TestClient, email: str, password: str) -> str:
    """辅助：登录并返回 access_token。"""
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    token: str = resp.json()["access_token"]
    return token


def _make_admin(db_session: Session, email: str = "admin@uni.edu") -> User:
    """创建一个 ACTIVE 的 System Admin 用户。"""
    tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
    db_session.flush()
    admin = User(
        tenant_id=tenant.id,
        email=email,
        password_hash=hash_password("AdminPass1!"),
        status=UserStatus.ACTIVE,
        display_name="Admin",
    )
    db_session.add(admin)
    db_session.flush()
    assign_role(db_session, user_id=admin.id, role_name=RoleName.SYSTEM_ADMIN.value)
    return admin


# --------------------------------------------------------------------------- #
# 管理端守卫
# --------------------------------------------------------------------------- #
class TestAdminGuard:
    def test_student_cannot_access_admin(self, client: TestClient, db_session: Session) -> None:
        """学生令牌不能访问管理端路由（设计测试矩阵：管理端独立路由守卫）。"""
        tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
        db_session.flush()
        student = create_student_user(
            db_session,
            tenant_id=tenant.id,
            email="student@example.com",
            password_hash=hash_password("ValidPass1!"),
        )
        student.status = UserStatus.ACTIVE
        db_session.flush()

        token = _login(client, "student@example.com", "ValidPass1!")
        resp = client.get(
            "/api/v1/admin/registrations/pending",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_admin_can_access_pending_list(self, client: TestClient, db_session: Session) -> None:
        _make_admin(db_session)
        token = _login(client, "admin@uni.edu", "AdminPass1!")
        resp = client.get(
            "/api/v1/admin/registrations/pending",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# 审核流转
# --------------------------------------------------------------------------- #
class TestRegistrationApproval:
    def test_registration_reads_and_decisions_are_tenant_scoped(
        self, client: TestClient, db_session: Session
    ) -> None:
        _make_admin(db_session)
        foreign_tenant = get_or_create_tenant(
            db_session, slug="foreign-review", name="Foreign Review"
        )
        db_session.flush()
        foreign = create_student_user(
            db_session,
            tenant_id=foreign_tenant.id,
            email="foreign-pending@example.com",
            password_hash=hash_password("ValidPass1!"),
        )
        token = _login(client, "admin@uni.edu", "AdminPass1!")

        pending = client.get(
            "/api/v1/admin/registrations/pending",
            headers={"Authorization": f"Bearer {token}"},
        )
        decision = client.post(
            f"/api/v1/admin/registrations/{foreign.id}/approve",
            json={},
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "foreign-registration-decision",
            },
        )

        assert pending.status_code == 200
        assert all(item["user_id"] != str(foreign.id) for item in pending.json())
        assert decision.status_code == 404
        assert foreign.status == UserStatus.PENDING

    def test_approve_pending_user(self, client: TestClient, db_session: Session) -> None:
        admin = _make_admin(db_session)
        tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
        db_session.flush()
        pending = create_student_user(
            db_session,
            tenant_id=tenant.id,
            email="pending@example.com",
            password_hash=hash_password("ValidPass1!"),
        )
        admin_token = _login(client, "admin@uni.edu", "AdminPass1!")

        resp = client.post(
            f"/api/v1/admin/registrations/{pending.id}/approve",
            json={},
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Idempotency-Key": "approve-pending-user",
                "x-trace-id": "trc_approve_test",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACTIVE"
        replay = client.post(
            f"/api/v1/admin/registrations/{pending.id}/approve",
            json={},
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Idempotency-Key": "approve-pending-user",
            },
        )
        assert replay.status_code == 200
        assert replay.json() == resp.json()

        # 批准后能登录。
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "pending@example.com", "password": "ValidPass1!"},
        )
        assert login_resp.status_code == 200

        audit = db_session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "REGISTRATION_APPROVED",
                AuditEvent.resource_id == str(pending.id),
            )
        )
        assert audit is not None
        assert audit.actor_user_id == admin.id
        assert audit.trace_id == "trc_approve_test"

        outbox = db_session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "REGISTRATION_APPROVED",
                OutboxEvent.aggregate_id == str(pending.id),
            )
        )
        assert outbox is not None
        assert outbox.trace_id == "trc_approve_test"

    def test_reject_pending_user(self, client: TestClient, db_session: Session) -> None:
        _make_admin(db_session)
        tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
        db_session.flush()
        pending = create_student_user(
            db_session,
            tenant_id=tenant.id,
            email="rejectme@example.com",
            password_hash=hash_password("ValidPass1!"),
        )
        admin_token = _login(client, "admin@uni.edu", "AdminPass1!")

        resp = client.post(
            f"/api/v1/admin/registrations/{pending.id}/reject",
            json={},
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Idempotency-Key": "reject-pending-user",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "REJECTED"

        # REJECTED 用户不能登录。
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "rejectme@example.com", "password": "ValidPass1!"},
        )
        assert login_resp.status_code == 403


# --------------------------------------------------------------------------- #
# demo 租户重置
# --------------------------------------------------------------------------- #
class TestDemoTenantReset:
    def test_reset_only_affects_demo_tenant(self, client: TestClient, db_session: Session) -> None:
        """重置 demo 租户不影响其他租户（设计验收：demo reset leaves other tenants unchanged）。"""
        admin = _make_admin(db_session)
        admin_token = _login(client, "admin@uni.edu", "AdminPass1!")

        # 创建 demo 租户 + 其下的用户。
        demo = get_or_create_tenant(
            db_session, slug="demo", name="Demo", tenant_type=TenantType.DEMO
        )
        db_session.flush()
        demo_user = create_student_user(
            db_session,
            tenant_id=demo.id,
            email="demo-user@demo.local",
            password_hash="not-used",
        )

        # 创建标准租户 + 其下的用户（不应被重置影响）。
        standard = get_or_create_tenant(
            db_session, slug="standard", name="Standard", tenant_type=TenantType.STANDARD
        )
        db_session.flush()
        standard_user = create_student_user(
            db_session,
            tenant_id=standard.id,
            email="std-user@std.local",
            password_hash="not-used",
        )
        demo_users_before_reset = db_session.scalar(
            select(func.count()).select_from(User).where(User.tenant_id == demo.id)
        )

        # 重置 demo 租户。
        resp = client.post(
            f"/api/v1/admin/tenants/{demo.id}/reset",
            json={"confirmation": f"RESET DEMO TENANT {demo.id}"},
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Idempotency-Key": "legacy-demo-reset",
                "x-trace-id": "trc_demo_reset",
            },
        )
        assert resp.status_code == 200

        # demo 用户被删除。
        from app.services import get_user_by_id

        assert get_user_by_id(db_session, demo_user.id) is None
        demo_guest = get_user_by_email(
            db_session,
            tenant_id=demo.id,
            email="guest@demo.pymentor.dev",
        )
        assert demo_guest is not None
        assert demo_guest.status == UserStatus.ACTIVE
        assert get_user_roles(db_session, demo_guest.id) == [RoleName.DEMO_GUEST.value]

        demo_login = client.post("/api/v1/auth/demo")
        assert demo_login.status_code == 200, demo_login.text
        # 标准租户用户不受影响。
        assert get_user_by_id(db_session, standard_user.id) is not None

        audit = db_session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "DEMO_TENANT_RESET",
                AuditEvent.resource_id == str(demo.id),
            )
        )
        assert audit is not None
        assert audit.actor_user_id == admin.id
        assert audit.trace_id == "trc_demo_reset"
        assert audit.detail["users_removed"] == demo_users_before_reset

        outbox = db_session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "DEMO_TENANT_RESET",
                OutboxEvent.aggregate_id == str(demo.id),
            )
        )
        assert outbox is not None
        assert outbox.trace_id == "trc_demo_reset"

    def test_non_admin_cannot_reset(self, client: TestClient, db_session: Session) -> None:
        """非 System Admin 不能重置租户。"""
        tenant = get_or_create_tenant(
            db_session, slug="demo", name="Demo", tenant_type=TenantType.DEMO
        )
        # 用 Course Admin（管理端角色但非 System Admin）。
        course_admin = _make_admin(db_session, email="ca@uni.edu")
        db_session.flush()
        # 移除 SYSTEM_ADMIN，改为 COURSE_ADMIN。
        from sqlalchemy import delete

        from app.models.identity import UserRole

        db_session.execute(delete(UserRole).where(UserRole.user_id == course_admin.id))
        db_session.flush()
        assign_role(db_session, user_id=course_admin.id, role_name=RoleName.COURSE_ADMIN.value)

        token = _login(client, "ca@uni.edu", "AdminPass1!")
        resp = client.post(
            f"/api/v1/admin/tenants/{tenant.id}/reset",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# bootstrap 幂等
# --------------------------------------------------------------------------- #
class TestBootstrap:
    def test_bootstrap_creates_admin_when_none(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """配置环境变量后，bootstrap 创建初始 admin。"""
        monkeypatch.setenv("PYMENTOR_INITIAL_ADMIN_EMAIL", "boot@pymentor.dev")
        monkeypatch.setenv("PYMENTOR_INITIAL_ADMIN_PASSWORD", "BootPass1!")

        # 重新加载 settings 以读取新的环境变量。
        from app import bootstrap as bootstrap_mod

        bootstrap_mod._settings = type(bootstrap_mod._settings)(
            initial_admin_email="boot@pymentor.dev",
            initial_admin_password="BootPass1!",
            database_url=bootstrap_mod._settings.database_url,
            jwt_secret=bootstrap_mod._settings.jwt_secret,
        )

        created = bootstrap_mod.bootstrap_initial_admin(db_session)
        assert created is not None
        roles = get_user_roles(db_session, created.id)
        assert RoleName.SYSTEM_ADMIN.value in roles

    def test_bootstrap_idempotent(self, db_session: Session) -> None:
        """重复执行 bootstrap 不创建重复 admin。"""
        from app import bootstrap as bootstrap_mod

        bootstrap_mod._settings = type(bootstrap_mod._settings)(
            initial_admin_email="boot2@pymentor.dev",
            initial_admin_password="BootPass1!",
            database_url=bootstrap_mod._settings.database_url,
            jwt_secret=bootstrap_mod._settings.jwt_secret,
        )

        first = bootstrap_mod.bootstrap_initial_admin(db_session)
        assert first is not None
        # 第二次：已有 admin，不创建。
        second = bootstrap_mod.bootstrap_initial_admin(db_session)
        assert second is None

    def test_bootstrap_rejects_non_email_admin(self, db_session: Session) -> None:
        """BE-029: 非法 email（无 @）在 bootstrap 阶段就被拒绝，不写入数据库。

        V1.0 incident: ``PYMENTOR_INITIAL_ADMIN_EMAIL=admin`` 被 bootstrap 接受并
        写入 users 表，但 ``POST /api/v1/auth/login`` 用 Pydantic EmailStr 严格
        校验，导致该账号无法登录，需手工 SQL 更正。此测试锁住该回归。

        同源校验：``EmailStr`` 还会拒绝保留 TLD（如 ``.local``），所以 v1.0 测试
        用的 ``boot@admin.local`` 也一并改为合法的 ``@pymentor.dev``。
        """
        from app import bootstrap as bootstrap_mod

        bootstrap_mod._settings = type(bootstrap_mod._settings)(
            initial_admin_email="admin",  # 无 @，不是合法 email
            initial_admin_password="BootPass1!",
            database_url=bootstrap_mod._settings.database_url,
            jwt_secret=bootstrap_mod._settings.jwt_secret,
        )

        # 非法 email 必须在写入前抛出明确异常，而不是静默创建无法登录的账号。
        with pytest.raises(ValueError, match=r"(?i)initial_admin_email.*email"):
            bootstrap_mod.bootstrap_initial_admin(db_session)

        # 并且不能有 admin@ 行残留在 users 表里。
        from sqlalchemy import select

        from app.models.identity import User

        leftover = db_session.scalar(select(User).where(User.email == "admin"))
        assert leftover is None

    def test_bootstrap_rejects_reserved_tld(self, db_session: Session) -> None:
        """BE-029: EmailStr 拒绝保留 TLD（.local），bootstrap 同源拒绝。"""
        from app import bootstrap as bootstrap_mod

        bootstrap_mod._settings = type(bootstrap_mod._settings)(
            initial_admin_email="admin@pymentor.local",  # .local 是保留 TLD
            initial_admin_password="BootPass1!",
            database_url=bootstrap_mod._settings.database_url,
            jwt_secret=bootstrap_mod._settings.jwt_secret,
        )
        with pytest.raises(ValueError, match=r"(?i)initial_admin_email.*email"):
            bootstrap_mod.bootstrap_initial_admin(db_session)

    def test_bootstrap_accepts_valid_email_after_reject(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BE-029: 拒绝非法 email 后，合法 email 仍能正常 bootstrap（无状态残留）。"""
        from app import bootstrap as bootstrap_mod

        # 第一次：非法 email，应抛 ValueError。
        bootstrap_mod._settings = type(bootstrap_mod._settings)(
            initial_admin_email="not-an-email",
            initial_admin_password="BootPass1!",
            database_url=bootstrap_mod._settings.database_url,
            jwt_secret=bootstrap_mod._settings.jwt_secret,
        )
        with pytest.raises(ValueError):
            bootstrap_mod.bootstrap_initial_admin(db_session)

        # 第二次：合法 email，应成功创建。
        bootstrap_mod._settings = type(bootstrap_mod._settings)(
            initial_admin_email="valid@pymentor.dev",
            initial_admin_password="BootPass1!",
            database_url=bootstrap_mod._settings.database_url,
            jwt_secret=bootstrap_mod._settings.jwt_secret,
        )
        created = bootstrap_mod.bootstrap_initial_admin(db_session)
        assert created is not None
        assert created.email == "valid@pymentor.dev"

    def test_seed_demo_tenant_creates_guest(self, db_session: Session) -> None:
        """seed_demo_tenant 创建 demo 租户与 Demo Guest 用户。"""
        from app.bootstrap import seed_demo_tenant

        seed_demo_tenant(db_session)

        from sqlalchemy import select

        from app.services import get_user_by_email

        demo = db_session.scalar(select(Tenant).where(Tenant.slug == "demo"))
        assert demo is not None
        assert demo.type == TenantType.DEMO

        guest = get_user_by_email(
            db_session,
            tenant_id=demo.id,
            email="guest@demo.pymentor.dev",
        )
        assert guest is not None
        roles = get_user_roles(db_session, guest.id)
        assert RoleName.DEMO_GUEST.value in roles
