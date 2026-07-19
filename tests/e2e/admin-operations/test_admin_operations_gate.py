"""INT-005 cross-route acceptance for least-privilege admin operations."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.system_maintenance import get_database_maintenance
from app.api.system_observability import ComponentProbe, get_system_health_probe
from app.db import get_db
from app.main import create_app
from app.models import (
    AgentRun,
    AgentToolCall,
    AuditEvent,
    DatabaseBackup,
    MaintenanceOperation,
    MasteryState,
    MasteryStatus,
    OutboxEvent,
    RoleName,
    Tenant,
    TenantType,
    User,
    UserStatus,
)
from app.observability import record_operational_log, record_provider_call
from app.providers import ProviderType
from app.security import create_access_token
from app.services import assign_role, create_student_user

COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")
NODE_ID = UUID("9512e5ec-f547-51b3-b0df-c5b3a877da9e")


@dataclass(frozen=True, slots=True)
class BackupArtifact:
    object_key: str
    digest: str
    size_bytes: int


class ControlledMaintenance:
    """Bounded artifact port; formal operation state remains in PostgreSQL."""

    requires_released_transaction = False

    def __init__(self) -> None:
        self.fail_restore = False
        self.backup_calls: list[UUID] = []
        self.restore_calls: list[tuple[str, str]] = []

    def create_backup(self, backup_id: UUID) -> BackupArtifact:
        self.backup_calls.append(backup_id)
        return BackupArtifact(
            object_key=f"int-005/{backup_id}.dump",
            digest="a" * 64,
            size_bytes=8192,
        )

    def restore_backup(self, *, object_key: str, expected_digest: str) -> None:
        self.restore_calls.append((object_key, expected_digest))
        if self.fail_restore:
            raise RuntimeError("restore failed with secret=must-not-leak")


@pytest.fixture()
def maintenance() -> ControlledMaintenance:
    return ControlledMaintenance()


@pytest.fixture()
def client(
    db_session: Session,
    maintenance: ControlledMaintenance,
) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_database_maintenance] = lambda: maintenance
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _tenant(db: Session, label: str, *, demo: bool = False) -> Tenant:
    tenant = Tenant(
        slug=f"int-005-{label}-{uuid4().hex}",
        name=f"INT-005 {label}",
        type=TenantType.DEMO if demo else TenantType.STANDARD,
    )
    db.add(tenant)
    db.flush()
    return tenant


def _user(db: Session, tenant: Tenant, role: RoleName, label: str) -> User:
    user = User(
        tenant_id=tenant.id,
        email=f"int-005-{label}-{uuid4().hex}@example.test",
        password_hash="not-used-by-token-test",
        status=UserStatus.ACTIVE,
        display_name=label,
    )
    db.add(user)
    db.flush()
    assign_role(db, user_id=user.id, role_name=role.value)
    return user


def _student(db: Session, tenant: Tenant, label: str) -> User:
    student = create_student_user(
        db,
        tenant_id=tenant.id,
        email=f"int-005-{label}-{uuid4().hex}@example.test",
        password_hash="not-used-by-token-test",
        student_no=f"INT005-{uuid4().hex[:10]}",
        display_name=label,
    )
    student.status = UserStatus.ACTIVE
    db.flush()
    return student


def _token(user: User, role: RoleName) -> str:
    token, _, _ = create_access_token(
        user_id=str(user.id),
        tenant_id=str(user.tenant_id),
        roles=[role.value],
    )
    return token


def _headers(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def test_admin_reads_observability_and_replay_are_scoped_paginated_and_redacted(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = _tenant(db_session, "read")
    foreign_tenant = _tenant(db_session, "foreign")
    system_admin = _user(db_session, tenant, RoleName.SYSTEM_ADMIN, "System Admin")
    course_admin = _user(db_session, tenant, RoleName.COURSE_ADMIN, "Course Admin")
    search = f"Live-{uuid4().hex}"
    first = _student(db_session, tenant, f"{search}-A")
    second = _student(db_session, tenant, f"{search}-B")
    foreign = _student(db_session, foreign_tenant, f"{search}-Foreign")
    system_token = _token(system_admin, RoleName.SYSTEM_ADMIN)
    course_token = _token(course_admin, RoleName.COURSE_ADMIN)
    student_token = _token(first, RoleName.STUDENT)

    run = AgentRun(
        external_run_id=f"int-005-run-{uuid4().hex}",
        event_id=f"int-005-event-{uuid4().hex}",
        trace_id=f"int-005-trace-{uuid4().hex}",
        tenant_id=tenant.id,
        student_id=first.id,
        status="SUCCEEDED",
        route="resource",
        latest_sequence=2,
        checkpoint_thread_id=f"thread-{uuid4().hex}",
        latest_checkpoint_id=f"checkpoint-{uuid4().hex}",
        fallback_used=False,
        safe_input_snapshot={"api_key": "raw-provider-secret", "summary": "bounded"},
        safe_output_snapshot={"result": "safe"},
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        AgentToolCall(
            tenant_id=tenant.id,
            agent_run_id=run.id,
            sequence=1,
            node="resource",
            tool_name="knowledge_search",
            event_type="TOOL_COMPLETED",
            status="SUCCEEDED",
            argument_digest="2" * 64,
            result_digest="3" * 64,
            latency_ms=12,
            retry_count=0,
            occurred_at=datetime.now(UTC),
        )
    )
    now = datetime.now(UTC) - timedelta(minutes=1)
    record_provider_call(
        db_session,
        tenant_id=tenant.id,
        provider_type=ProviderType.LLM,
        vendor="int-005-vendor",
        model="int-005-model",
        operation="CHAT",
        outcome="FAILED",
        latency_ms=40,
        rate_limited=True,
        trace_id="int-005-metric-trace",
        created_at=now,
    )
    record_operational_log(
        db_session,
        tenant_id=tenant.id,
        source="REQUEST",
        level="INFO",
        message="int-005 request",
        trace_id="int-005-request-trace",
        context={"authorization": "Bearer must-not-leak"},
        created_at=now,
    )
    db_session.add(
        AuditEvent(
            tenant_id=tenant.id,
            actor_user_id=system_admin.id,
            action="INT005_SAFE_AUDIT",
            resource_type="acceptance",
            resource_id="int-005",
            trace_id="int-005-audit-trace",
            detail={"api_key": "must-not-leak"},
            created_at=now + timedelta(seconds=1),
        )
    )
    db_session.flush()

    denied = client.get("/api/v1/admin/students", headers=_headers(student_token))
    page_one = client.get(
        "/api/v1/admin/students",
        params={"page": 1, "page_size": 1, "q": search},
        headers=_headers(course_token),
    )
    page_two = client.get(
        "/api/v1/admin/students",
        params={"page": 2, "page_size": 1, "q": search},
        headers=_headers(course_token),
    )
    assert denied.status_code == 403
    assert page_one.status_code == page_two.status_code == 200
    assert page_one.json()["page"] == {
        "number": 1,
        "size": 1,
        "total_items": 2,
        "total_pages": 2,
    }
    listed = {page_one.json()["items"][0]["id"], page_two.json()["items"][0]["id"]}
    assert listed == {str(first.id), str(second.id)}
    assert str(foreign.id) not in page_one.text + page_two.text
    assert "password" not in page_one.text.lower()

    replay = client.get(
        f"/api/v1/admin/agent-runs/{run.external_run_id}",
        headers=_headers(course_token),
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["tool_calls"][0]["sequence"] == 1
    assert replay.json()["input_snapshot"]["api_key"] == "***"
    assert "raw-provider-secret" not in replay.text

    app = client.app
    assert isinstance(app, FastAPI)
    app.dependency_overrides[get_system_health_probe] = lambda: (
        lambda _db: [
            ComponentProbe("api", "HEALTHY", 1, "ready"),
            ComponentProbe("worker", "DEGRADED", 25, "unavailable"),
        ]
    )
    health = client.get("/api/v1/admin/system/health", headers=_headers(course_token))
    metrics_denied = client.get("/api/v1/admin/system/metrics", headers=_headers(course_token))
    metrics = client.get("/api/v1/admin/system/metrics", headers=_headers(system_token))
    logs = client.get(
        "/api/v1/admin/system/logs",
        params={"source": "AUDIT", "page": 1, "page_size": 20},
        headers=_headers(system_token),
    )
    database = client.get("/api/v1/admin/system/db", headers=_headers(system_token))
    assert health.status_code == 200 and health.json()["status"] == "DEGRADED"
    assert metrics_denied.status_code == 403
    assert metrics.status_code == 200
    assert any(item["vendor"] == "int-005-vendor" for item in metrics.json()["items"])
    assert logs.status_code == 200
    assert any(item["message"] == "INT005_SAFE_AUDIT" for item in logs.json()["items"])
    assert "must-not-leak" not in logs.text
    assert database.status_code == 200
    assert database.json()["engine"] == "PostgreSQL"
    assert "postgresql+psycopg" not in database.text.lower()

    master_key = bytes(range(32))
    monkeypatch.setenv(
        "PYMENTOR_PROVIDER_MASTER_KEY",
        base64.urlsafe_b64encode(master_key).decode("ascii"),
    )
    provider_secret = "int-005-plaintext-provider-secret"
    course_denied = client.get("/api/v1/admin/providers", headers=_headers(course_token))
    created = client.post(
        "/api/v1/admin/providers",
        json={
            "provider_type": "LLM",
            "vendor": "int-005-provider",
            "model": "safe-model",
            "api_key": provider_secret,
            "endpoint": "https://provider.example.test/v1/models",
            "params": {"temperature": 0.1},
            "enabled": True,
        },
        headers=_headers(system_token, f"int-005-provider-{uuid4().hex}"),
    )
    providers = client.get("/api/v1/admin/providers", headers=_headers(system_token))
    assert course_denied.status_code == 403
    assert created.status_code == 201, created.text
    assert providers.status_code == 200
    assert provider_secret not in created.text + providers.text
    assert created.json()["api_key_masked"].endswith("cret")


def test_maintenance_is_confirmed_idempotent_audited_and_mastery_safe(
    client: TestClient,
    db_session: Session,
    maintenance: ControlledMaintenance,
) -> None:
    tenant = _tenant(db_session, "maintenance")
    system_admin = _user(db_session, tenant, RoleName.SYSTEM_ADMIN, "System Admin")
    token = _token(system_admin, RoleName.SYSTEM_ADMIN)
    delete_target = _student(db_session, tenant, "Delete Target")
    protected_student = _student(db_session, tenant, "Protected Student")
    mastery = MasteryState(
        tenant_id=tenant.id,
        student_id=protected_student.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        status=MasteryStatus.LEARNING,
        version=7,
    )
    db_session.add(mastery)
    demo = _tenant(db_session, "demo", demo=True)
    _student(db_session, demo, "Disposable Demo Student")
    db_session.flush()
    mastery_id = mastery.id

    wrong_delete = client.request(
        "DELETE",
        f"/api/v1/admin/students/{delete_target.id}",
        json={"confirmation": "DELETE STUDENT"},
        headers=_headers(token, f"int-005-delete-wrong-{uuid4().hex}"),
    )
    delete_key = f"int-005-delete-{uuid4().hex}"
    delete_request = {"confirmation": f"DELETE STUDENT {delete_target.id}"}
    first_delete = client.request(
        "DELETE",
        f"/api/v1/admin/students/{delete_target.id}",
        json=delete_request,
        headers=_headers(token, delete_key),
    )
    replay_delete = client.request(
        "DELETE",
        f"/api/v1/admin/students/{delete_target.id}",
        json=delete_request,
        headers=_headers(token, delete_key),
    )
    assert wrong_delete.status_code == 422
    assert first_delete.status_code == replay_delete.status_code == 200
    assert first_delete.json() == replay_delete.json()
    assert db_session.get(User, delete_target.id) is None

    reset_key = f"int-005-reset-{uuid4().hex}"
    reset_request = {"confirmation": f"RESET DEMO TENANT {demo.id}"}
    first_reset = client.post(
        f"/api/v1/admin/tenants/{demo.id}/reset",
        json=reset_request,
        headers=_headers(token, reset_key),
    )
    replay_reset = client.post(
        f"/api/v1/admin/tenants/{demo.id}/reset",
        json=reset_request,
        headers=_headers(token, reset_key),
    )
    assert first_reset.status_code == replay_reset.status_code == 200
    assert first_reset.json() == replay_reset.json()

    missing_key = client.post(
        "/api/v1/admin/system/db/backup",
        json={"confirmation": "BACKUP DATABASE"},
        headers=_headers(token),
    )
    wrong_backup = client.post(
        "/api/v1/admin/system/db/backup",
        json={"confirmation": "backup database"},
        headers=_headers(token, f"int-005-backup-wrong-{uuid4().hex}"),
    )
    backup_key = f"int-005-backup-{uuid4().hex}"
    first_backup = client.post(
        "/api/v1/admin/system/db/backup",
        json={"confirmation": "BACKUP DATABASE"},
        headers={**_headers(token, backup_key), "x-trace-id": "int-005-backup-trace"},
    )
    replay_backup = client.post(
        "/api/v1/admin/system/db/backup",
        json={"confirmation": "BACKUP DATABASE"},
        headers=_headers(token, backup_key),
    )
    assert missing_key.status_code == wrong_backup.status_code == 422
    assert first_backup.status_code == replay_backup.status_code == 201
    assert first_backup.json() == replay_backup.json()
    assert len(maintenance.backup_calls) == 1
    backup_id = UUID(first_backup.json()["id"])
    backup = db_session.get(DatabaseBackup, backup_id)
    assert backup is not None and backup.status == "AVAILABLE"

    maintenance.fail_restore = True
    failure_key = f"int-005-restore-failure-{uuid4().hex}"
    restore_request = {
        "backup_id": str(backup_id),
        "confirmation": "RESTORE DATABASE",
    }
    failed_restore = client.post(
        "/api/v1/admin/system/db/restore",
        json=restore_request,
        headers={**_headers(token, failure_key), "x-trace-id": "int-005-restore-failed"},
    )
    replay_failure = client.post(
        "/api/v1/admin/system/db/restore",
        json=restore_request,
        headers=_headers(token, failure_key),
    )
    assert failed_restore.status_code == replay_failure.status_code == 503
    assert failed_restore.json() == replay_failure.json()
    assert "must-not-leak" not in failed_restore.text
    assert len(maintenance.restore_calls) == 1

    maintenance.fail_restore = False
    success_key = f"int-005-restore-success-{uuid4().hex}"
    restored = client.post(
        "/api/v1/admin/system/db/restore",
        json=restore_request,
        headers=_headers(token, success_key),
    )
    replay_restore = client.post(
        "/api/v1/admin/system/db/restore",
        json=restore_request,
        headers=_headers(token, success_key),
    )
    assert restored.status_code == replay_restore.status_code == 200
    assert restored.json() == replay_restore.json()
    assert restored.json()["status"] == "SUCCEEDED"
    assert len(maintenance.restore_calls) == 2

    db_session.expire_all()
    unchanged = db_session.get(MasteryState, mastery_id)
    assert unchanged is not None
    assert unchanged.status == MasteryStatus.LEARNING
    assert unchanged.version == 7
    actions = set(db_session.scalars(select(AuditEvent.action)))
    assert {
        "STUDENT_DATA_DELETED",
        "DEMO_TENANT_RESET",
        "DATABASE_BACKUP_CREATED",
        "DATABASE_RESTORE_FAILED",
        "DATABASE_RESTORED",
    } <= actions
    operation_statuses = set(
        db_session.execute(
            select(MaintenanceOperation.operation_type, MaintenanceOperation.status)
        ).all()
    )
    assert ("DATABASE_RESTORE", "FAILED") in operation_statuses
    assert ("DATABASE_RESTORE", "SUCCEEDED") in operation_statuses
    outbox_types = set(db_session.scalars(select(OutboxEvent.event_type)))
    assert {
        "STUDENT_DATA_DELETED",
        "DEMO_TENANT_RESET",
        "DATABASE_BACKUP_CREATED",
        "DATABASE_RESTORED",
    } <= outbox_types
