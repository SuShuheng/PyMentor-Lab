"""BE-010 health, Provider metrics, and redacted log query tests."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.system_observability import ComponentProbe, get_system_health_probe
from app.db import get_db
from app.main import create_app
from app.models import AgentRun, AuditEvent, RoleName, Tenant, User, UserStatus
from app.observability import record_operational_log, record_provider_call
from app.providers import ProviderType
from app.security import create_access_token
from app.services import assign_role, get_or_create_tenant

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


@dataclass(slots=True)
class AdminContext:
    tenant: Tenant
    system_admin: User
    course_admin: User
    system_token: str
    course_token: str


@pytest.fixture()
def admin_context(db_session: Session) -> AdminContext:
    tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
    system_admin = _make_user(db_session, tenant, RoleName.SYSTEM_ADMIN)
    course_admin = _make_user(db_session, tenant, RoleName.COURSE_ADMIN)
    system_token, _, _ = create_access_token(
        user_id=str(system_admin.id),
        tenant_id=str(tenant.id),
        roles=[RoleName.SYSTEM_ADMIN.value],
    )
    course_token, _, _ = create_access_token(
        user_id=str(course_admin.id),
        tenant_id=str(tenant.id),
        roles=[RoleName.COURSE_ADMIN.value],
    )
    return AdminContext(tenant, system_admin, course_admin, system_token, course_token)


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _make_user(db: Session, tenant: Tenant, role: RoleName) -> User:
    user = User(
        tenant_id=tenant.id,
        email=f"{role.value.lower()}-{uuid4().hex}@example.com",
        password_hash="not-used-by-token-tests",
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    db.flush()
    assign_role(db, user_id=user.id, role_name=role.value)
    return user


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_board_reports_each_component_and_degraded_overall(
    client: TestClient, admin_context: AdminContext
) -> None:
    def _probe(_db: Session) -> list[ComponentProbe]:
        return [
            ComponentProbe("api", "HEALTHY", 0, "ready"),
            ComponentProbe("worker", "DEGRADED", 25, "unavailable"),
            ComponentProbe("sandbox", "HEALTHY", 4, "ready"),
            ComponentProbe("redis", "HEALTHY", 2, "ready"),
            ComponentProbe("postgresql", "HEALTHY", 3, "ready"),
            ComponentProbe("object_store", "HEALTHY", 5, "ready"),
        ]

    app = client.app
    assert isinstance(app, FastAPI)
    app.dependency_overrides[get_system_health_probe] = lambda: _probe

    response = client.get(
        "/api/v1/admin/system/health", headers=_headers(admin_context.course_token)
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "DEGRADED"
    assert [item["component"] for item in response.json()["components"]] == [
        "api",
        "worker",
        "sandbox",
        "redis",
        "postgresql",
        "object_store",
    ]
    assert "http://" not in response.text


def test_provider_metrics_are_tenant_scoped_filtered_and_aggregated(
    client: TestClient, db_session: Session, admin_context: AdminContext
) -> None:
    for latency, outcome, rate_limited in [
        (10, "SUCCEEDED", False),
        (20, "FAILED", False),
        (30, "FAILED", True),
    ]:
        record_provider_call(
            db_session,
            tenant_id=admin_context.tenant.id,
            provider_type=ProviderType.LLM,
            vendor="xfyun",
            model="spark-v4",
            operation="CHAT",
            outcome=outcome,
            latency_ms=latency,
            rate_limited=rate_limited,
            trace_id=f"trace-{latency}",
            created_at=NOW + timedelta(seconds=latency),
        )
    foreign = Tenant(slug=f"metrics-foreign-{uuid4().hex}", name="Foreign")
    db_session.add(foreign)
    db_session.flush()
    record_provider_call(
        db_session,
        tenant_id=foreign.id,
        provider_type=ProviderType.LLM,
        vendor="foreign",
        model="foreign-model",
        operation="CHAT",
        outcome="SUCCEEDED",
        latency_ms=999,
        rate_limited=False,
        trace_id="foreign-trace",
        created_at=NOW,
    )
    db_session.flush()

    denied = client.get(
        "/api/v1/admin/system/metrics", headers=_headers(admin_context.course_token)
    )
    response = client.get(
        "/api/v1/admin/system/metrics"
        "?since=2026-07-18T11:59:00Z&until=2026-07-18T12:02:00Z&provider_type=LLM",
        headers=_headers(admin_context.system_token),
    )

    assert denied.status_code == 403
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item == {
        "provider_type": "LLM",
        "vendor": "xfyun",
        "model": "spark-v4",
        "calls": 3,
        "errors": 2,
        "rate_limited": 1,
        "average_latency_ms": 20.0,
        "p95_latency_ms": 30,
        "error_rate": pytest.approx(2 / 3),
    }
    assert "foreign-model" not in response.text


def test_logs_merge_request_agent_and_audit_sources_without_secrets(
    client: TestClient, db_session: Session, admin_context: AdminContext
) -> None:
    record_operational_log(
        db_session,
        tenant_id=admin_context.tenant.id,
        source="REQUEST",
        level="INFO",
        message="request completed",
        trace_id="trace-request",
        context={"path": "/safe", "authorization": "Bearer secret-token"},
        created_at=NOW,
    )
    db_session.add(
        AuditEvent(
            tenant_id=admin_context.tenant.id,
            actor_user_id=admin_context.system_admin.id,
            action="SAFE_ADMIN_ACTION",
            resource_type="provider_config",
            resource_id="provider-1",
            trace_id="trace-audit",
            detail={"api_key": "must-not-leak", "changed_fields": ["enabled"]},
            created_at=NOW + timedelta(seconds=1),
        )
    )
    student = _make_user(db_session, admin_context.tenant, RoleName.STUDENT)
    db_session.add(
        AgentRun(
            external_run_id=f"run-{uuid4().hex}",
            event_id=f"event-{uuid4().hex}",
            trace_id="trace-agent",
            tenant_id=admin_context.tenant.id,
            student_id=student.id,
            status="FAILED",
            route="coach",
            latest_sequence=1,
            fallback_used=True,
            error_code="PROVIDER_UNAVAILABLE",
            safe_input_snapshot={"raw_prompt": "must-not-leak"},
            safe_output_snapshot={},
            created_at=NOW + timedelta(seconds=2),
        )
    )
    foreign = Tenant(slug=f"logs-foreign-{uuid4().hex}", name="Foreign")
    db_session.add(foreign)
    db_session.flush()
    record_operational_log(
        db_session,
        tenant_id=foreign.id,
        source="ERROR",
        level="ERROR",
        message="foreign error",
        trace_id="foreign-trace",
        context={},
        created_at=NOW,
    )
    db_session.flush()

    response = client.get(
        "/api/v1/admin/system/logs?page=1&page_size=20",
        headers=_headers(admin_context.system_token),
    )
    agent_only = client.get(
        "/api/v1/admin/system/logs?source=AGENT&page=1&page_size=20",
        headers=_headers(admin_context.system_token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page"]["total_items"] == 3
    assert {item["source"] for item in body["items"]} == {"REQUEST", "AUDIT", "AGENT"}
    assert "secret-token" not in response.text
    assert "must-not-leak" not in response.text
    assert "foreign error" not in response.text
    assert "***" in response.text
    assert agent_only.status_code == 200
    assert [item["source"] for item in agent_only.json()["items"]] == ["AGENT"]


def test_request_logging_persists_metadata_without_headers_or_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.config as config_module
    import app.db as db_module
    import app.observability as observability_module

    captured: dict[str, object] = {}

    class FakeSession:
        def __enter__(self) -> FakeSession:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def commit(self) -> None:
            captured["committed"] = True

    def _record(_db: object, **kwargs: object) -> None:
        captured.update(kwargs)

    app = create_app()
    original_settings = config_module.get_settings()
    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: SimpleNamespace(
            **{
                **original_settings.__dict__,
                "operational_log_persistence_enabled": True,
            }
        ),
    )
    monkeypatch.setattr(db_module, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(observability_module, "record_operational_log", _record)

    with TestClient(app) as test_client:
        response = test_client.request(
            "GET",
            "/health",
            headers={"authorization": "Bearer must-not-be-recorded"},
            json={"raw_prompt": "must-not-be-recorded"},
        )

    assert response.status_code == 200
    assert captured["source"] == "REQUEST"
    assert captured["message"] == "request completed"
    context = captured["context"]
    assert isinstance(context, dict)
    assert context["method"] == "GET"
    assert context["path"] == "/health"
    assert context["status_code"] == 200
    assert isinstance(context["duration_ms"], int)
    assert context["user_id"] is None
    assert "must-not-be-recorded" not in str(captured)
    assert captured["committed"] is True
