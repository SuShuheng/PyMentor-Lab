"""Security and failure-safety tests for BE-010 maintenance operations."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.system_maintenance import get_database_maintenance
from app.db import get_db
from app.main import create_app
from app.models import (
    AuditEvent,
    DatabaseBackup,
    MaintenanceOperation,
    OutboxEvent,
    Tenant,
    User,
)
from app.models.base import RoleName, TenantType, UserStatus
from app.security import hash_password
from app.services import assign_role, create_student_user, get_or_create_tenant


@dataclass(frozen=True, slots=True)
class FakeArtifact:
    object_key: str
    digest: str
    size_bytes: int


class FakeMaintenance:
    requires_released_transaction = False

    def __init__(self, *, restore_error: bool = False) -> None:
        self.restore_error = restore_error
        self.backup_calls: list[UUID] = []
        self.restore_calls: list[tuple[str, str]] = []

    def create_backup(self, backup_id: UUID) -> FakeArtifact:
        self.backup_calls.append(backup_id)
        return FakeArtifact(
            object_key=f"system-backups/{backup_id}.dump",
            digest="a" * 64,
            size_bytes=4096,
        )

    def restore_backup(self, *, object_key: str, expected_digest: str) -> None:
        self.restore_calls.append((object_key, expected_digest))
        if self.restore_error:
            raise RuntimeError("archive validation failed with secret=/should/not/leak")


@pytest.fixture()
def maintenance() -> FakeMaintenance:
    return FakeMaintenance()


@pytest.fixture()
def client(db_session: Session, maintenance: FakeMaintenance) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_database_maintenance] = lambda: maintenance
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _admin(db: Session, *, role: RoleName = RoleName.SYSTEM_ADMIN) -> User:
    tenant = get_or_create_tenant(db, slug="default", name="Default Tenant")
    db.flush()
    user = User(
        tenant_id=tenant.id,
        email=f"{role.value.lower()}@example.com",
        password_hash=hash_password("AdminPass1!"),
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    db.flush()
    assign_role(db, user_id=user.id, role_name=role.value)
    return user


def _login(client: TestClient, user: User) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "AdminPass1!"},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _headers(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def test_database_status_is_system_admin_only_and_redacted(
    client: TestClient, db_session: Session
) -> None:
    course_admin = _admin(db_session, role=RoleName.COURSE_ADMIN)
    denied = client.get("/api/v1/admin/system/db", headers=_headers(_login(client, course_admin)))
    assert denied.status_code == 403

    system_admin = _admin(db_session)
    response = client.get(
        "/api/v1/admin/system/db", headers=_headers(_login(client, system_admin))
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["connected"] is True
    assert payload["engine"] == "PostgreSQL"
    assert payload["database_size_bytes"] >= 0
    assert payload["table_count"] > 0
    assert payload["tables"]
    rendered = response.text.lower()
    assert "pymentor_dev" not in rendered
    assert "postgresql+psycopg" not in rendered
    assert "localhost" not in rendered


def test_backup_requires_confirmation_and_idempotency_then_replays(
    client: TestClient, db_session: Session, maintenance: FakeMaintenance
) -> None:
    admin = _admin(db_session)
    token = _login(client, admin)
    endpoint = "/api/v1/admin/system/db/backup"

    missing_key = client.post(
        endpoint,
        json={"confirmation": "BACKUP DATABASE"},
        headers=_headers(token),
    )
    assert missing_key.status_code == 422
    wrong = client.post(
        endpoint,
        json={"confirmation": "backup database"},
        headers=_headers(token, "backup-wrong"),
    )
    assert wrong.status_code == 422
    assert maintenance.backup_calls == []

    first = client.post(
        endpoint,
        json={"confirmation": "BACKUP DATABASE"},
        headers={**_headers(token, "backup-once"), "x-trace-id": "trace-backup"},
    )
    replay = client.post(
        endpoint,
        json={"confirmation": "BACKUP DATABASE"},
        headers=_headers(token, "backup-once"),
    )
    assert first.status_code == 201, first.text
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert len(maintenance.backup_calls) == 1
    backup = db_session.get(DatabaseBackup, UUID(first.json()["id"]))
    assert backup is not None
    assert backup.object_key.startswith("system-backups/")
    assert backup.digest == "a" * 64
    audit = db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == "DATABASE_BACKUP_CREATED")
    )
    assert audit is not None
    assert audit.trace_id == "trace-backup"
    assert audit.detail["confirmation_verified"] is True
    assert "confirmation" not in audit.detail


def test_restore_validates_backup_and_records_failure_without_mutating_data(
    client: TestClient, db_session: Session
) -> None:
    failing = FakeMaintenance(restore_error=True)
    app = client.app
    app.dependency_overrides[get_database_maintenance] = lambda: failing
    admin = _admin(db_session)
    token = _login(client, admin)
    backup = DatabaseBackup(
        tenant_id=admin.tenant_id,
        object_key="system-backups/known.dump",
        digest="b" * 64,
        size_bytes=100,
        status="AVAILABLE",
        created_by=admin.id,
    )
    db_session.add(backup)
    db_session.flush()
    tenant_count = db_session.scalar(select(func.count()).select_from(Tenant))

    response = client.post(
        "/api/v1/admin/system/db/restore",
        json={"backup_id": str(backup.id), "confirmation": "RESTORE DATABASE"},
        headers={**_headers(token, "restore-failure"), "x-trace-id": "trace-restore"},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert response.json()["trace_id"] == "trace-restore"
    assert "secret" not in response.text
    assert db_session.scalar(select(func.count()).select_from(Tenant)) == tenant_count
    operation = db_session.scalar(
        select(MaintenanceOperation).where(
            MaintenanceOperation.operation_type == "DATABASE_RESTORE"
        )
    )
    assert operation is not None
    assert operation.status == "FAILED"
    assert operation.error_code == "RESTORE_FAILED"
    audit = db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == "DATABASE_RESTORE_FAILED")
    )
    assert audit is not None
    assert audit.detail == {
        "backup_id": str(backup.id),
        "confirmation_verified": True,
        "error_code": "RESTORE_FAILED",
    }


def test_restore_success_is_audited_and_idempotent(
    client: TestClient, db_session: Session, maintenance: FakeMaintenance
) -> None:
    admin = _admin(db_session)
    token = _login(client, admin)
    backup = DatabaseBackup(
        tenant_id=admin.tenant_id,
        object_key="system-backups/success.dump",
        digest="c" * 64,
        size_bytes=512,
        status="AVAILABLE",
        created_by=admin.id,
    )
    db_session.add(backup)
    db_session.flush()
    request = {
        "backup_id": str(backup.id),
        "confirmation": "RESTORE DATABASE",
    }
    headers = _headers(token, "restore-success")

    first = client.post("/api/v1/admin/system/db/restore", json=request, headers=headers)
    replay = client.post("/api/v1/admin/system/db/restore", json=request, headers=headers)

    assert first.status_code == 200, first.text
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert maintenance.restore_calls == [(backup.object_key, backup.digest)]
    assert first.json()["status"] == "SUCCEEDED"
    audit = db_session.scalar(select(AuditEvent).where(AuditEvent.action == "DATABASE_RESTORED"))
    assert audit is not None
    assert audit.detail == {
        "backup_id": str(backup.id),
        "confirmation_verified": True,
    }
    outbox = db_session.scalar(
        select(OutboxEvent).where(OutboxEvent.event_type == "DATABASE_RESTORED")
    )
    assert outbox is not None
    assert outbox.aggregate_id == str(backup.id)


def test_student_delete_is_tenant_scoped_confirmed_idempotent_and_audited(
    client: TestClient, db_session: Session
) -> None:
    admin = _admin(db_session)
    token = _login(client, admin)
    student = create_student_user(
        db_session,
        tenant_id=admin.tenant_id,
        email="delete-me@maintenance.local",
        password_hash=hash_password("StudentPass1!"),
    )
    student.status = UserStatus.ACTIVE
    other_tenant = get_or_create_tenant(db_session, slug="delete-other", name="Other")
    db_session.flush()
    foreign = create_student_user(
        db_session,
        tenant_id=other_tenant.id,
        email="foreign@maintenance.local",
        password_hash=hash_password("StudentPass1!"),
    )
    db_session.flush()

    foreign_response = client.request(
        "DELETE",
        f"/api/v1/admin/students/{foreign.id}",
        json={"confirmation": f"DELETE STUDENT {foreign.id}"},
        headers=_headers(token, "delete-foreign"),
    )
    assert foreign_response.status_code == 404
    wrong = client.request(
        "DELETE",
        f"/api/v1/admin/students/{student.id}",
        json={"confirmation": "DELETE STUDENT"},
        headers=_headers(token, "delete-wrong"),
    )
    assert wrong.status_code == 422

    first = client.request(
        "DELETE",
        f"/api/v1/admin/students/{student.id}",
        json={"confirmation": f"DELETE STUDENT {student.id}"},
        headers=_headers(token, "delete-student"),
    )
    replay = client.request(
        "DELETE",
        f"/api/v1/admin/students/{student.id}",
        json={"confirmation": f"DELETE STUDENT {student.id}"},
        headers=_headers(token, "delete-student"),
    )
    assert first.status_code == 200, first.text
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert db_session.get(User, student.id) is None
    assert db_session.get(User, foreign.id) is not None
    audit = db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == "STUDENT_DATA_DELETED")
    )
    assert audit is not None
    assert audit.resource_id == str(student.id)
    assert "email" not in audit.detail


def test_demo_reset_requires_exact_confirmation_and_is_idempotent(
    client: TestClient, db_session: Session
) -> None:
    admin = _admin(db_session)
    token = _login(client, admin)
    demo = get_or_create_tenant(
        db_session, slug="maintenance-demo", name="Demo", tenant_type=TenantType.DEMO
    )
    db_session.flush()
    student = create_student_user(
        db_session,
        tenant_id=demo.id,
        email="guest@maintenance-demo.local",
        password_hash=hash_password("StudentPass1!"),
    )
    db_session.flush()
    endpoint = f"/api/v1/admin/tenants/{demo.id}/reset"
    denied = client.post(
        endpoint,
        json={"confirmation": "RESET DEMO TENANT"},
        headers=_headers(token),
    )
    assert denied.status_code == 422

    first = client.post(
        endpoint,
        json={"confirmation": f"RESET DEMO TENANT {demo.id}"},
        headers=_headers(token, "reset-demo"),
    )
    replay = client.post(
        endpoint,
        json={"confirmation": f"RESET DEMO TENANT {demo.id}"},
        headers=_headers(token, "reset-demo"),
    )
    assert first.status_code == 200, first.text
    assert replay.json() == first.json()
    assert db_session.get(User, student.id) is None
