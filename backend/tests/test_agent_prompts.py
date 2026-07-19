"""BE-020 versioned Agent prompt template storage + tuning API tests.

A System Admin can version, publish, and audit per-LangGraph-node system prompts.
The current published version is the only one a runtime Worker reads. Non-admins
are denied; versions are monotonic per node; publishing one version atomically
unpublishes the others for the same node.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import create_app
from app.models import AuditEvent, RoleName, Tenant, User, UserStatus
from app.security import create_access_token
from app.services import assign_role, get_or_create_tenant

NODES = ["orchestrator", "profile", "path", "resource", "coach", "assessment"]


@dataclass(slots=True)
class PromptContext:
    system_admin: User
    course_admin: User
    student: User
    system_token: str
    course_token: str
    student_token: str


@pytest.fixture()
def prompt_context(db_session: Session) -> PromptContext:
    tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
    system_admin = _make_user(db_session, tenant, RoleName.SYSTEM_ADMIN)
    course_admin = _make_user(db_session, tenant, RoleName.COURSE_ADMIN)
    student = _make_user(db_session, tenant, RoleName.STUDENT)
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
    student_token, _, _ = create_access_token(
        user_id=str(student.id),
        tenant_id=str(tenant.id),
        roles=[RoleName.STUDENT.value],
    )
    return PromptContext(
        system_admin, course_admin, student, system_token, course_token, student_token
    )


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
        display_name=role.value,
    )
    db.add(user)
    db.flush()
    assign_role(db, user_id=user.id, role_name=role.value)
    return user


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_version(
    client: TestClient,
    context: PromptContext,
    node: str,
    *,
    prompt: str | None = None,
    key: str | None = None,
) -> dict[str, object]:
    headers = _headers(context.system_token)
    headers["Idempotency-Key"] = key or f"prompt-{node}-{uuid4().hex}"
    response = client.post(
        f"/api/v1/admin/agent-prompts/{node}",
        json={"system_prompt": prompt or f"You are the {node} node."},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert isinstance(result, dict)
    return result


def test_create_version_records_draft_and_monotonic_versions_per_node(
    client: TestClient, prompt_context: PromptContext
) -> None:
    first = _create_version(client, prompt_context, "orchestrator", prompt="v1 body")
    second = _create_version(client, prompt_context, "orchestrator", prompt="v2 body")

    assert first["node"] == "orchestrator"
    assert first["version"] == 1
    assert first["published"] is False
    assert first["system_prompt"] == "v1 body"
    assert second["version"] == 2
    assert second["published"] is False

    other_node = _create_version(client, prompt_context, "coach", prompt="coach v1")
    assert other_node["version"] == 1


def test_publish_sets_published_and_unpublishes_others(
    client: TestClient, prompt_context: PromptContext, db_session: Session
) -> None:
    from app.models.agent import AgentPromptTemplate

    first = _create_version(client, prompt_context, "coach", prompt="coach v1")
    second = _create_version(client, prompt_context, "coach", prompt="coach v2")

    publish = client.post(
        f"/api/v1/admin/agent-prompts/coach/{first['version']}/publish",
        headers=_headers(prompt_context.system_token),
    )
    assert publish.status_code == 200, publish.text
    assert publish.json()["published"] is True

    # Current reflects the published one.
    current = client.get(
        "/api/v1/admin/agent-prompts/coach", headers=_headers(prompt_context.system_token)
    )
    assert current.status_code == 200
    assert current.json()["version"] == first["version"]

    # Publishing the second atomically unpublishes the first.
    publish2 = client.post(
        f"/api/v1/admin/agent-prompts/coach/{second['version']}/publish",
        headers=_headers(prompt_context.system_token),
    )
    assert publish2.status_code == 200
    published_rows = list(
        db_session.scalars(
            select(AgentPromptTemplate).where(
                AgentPromptTemplate.tenant_id == prompt_context.system_admin.tenant_id,
                AgentPromptTemplate.node == "coach",
                AgentPromptTemplate.published.is_(True),
            )
        )
    )
    assert len(published_rows) == 1
    assert published_rows[0].version == second["version"]


def test_current_returns_none_when_no_published_version(
    client: TestClient, prompt_context: PromptContext
) -> None:
    _create_version(client, prompt_context, "path")  # draft only, never published
    current = client.get(
        "/api/v1/admin/agent-prompts/path", headers=_headers(prompt_context.system_token)
    )
    assert current.status_code == 200
    assert current.json() is None


def test_history_returns_all_versions_newest_first(
    client: TestClient, prompt_context: PromptContext
) -> None:
    _create_version(client, prompt_context, "profile", prompt="p1")
    _create_version(client, prompt_context, "profile", prompt="p2")
    _create_version(client, prompt_context, "profile", prompt="p3")

    history = client.get(
        "/api/v1/admin/agent-prompts/profile/history",
        headers=_headers(prompt_context.system_token),
    )
    assert history.status_code == 200
    items = history.json()["items"]
    assert [item["version"] for item in items] == [3, 2, 1]


def test_publish_writes_audit_event(
    client: TestClient, prompt_context: PromptContext, db_session: Session
) -> None:
    created = _create_version(client, prompt_context, "assessment")
    publish = client.post(
        f"/api/v1/admin/agent-prompts/assessment/{created['version']}/publish",
        headers=_headers(prompt_context.system_token),
    )
    assert publish.status_code == 200

    actions = set(
        db_session.scalars(
            select(AuditEvent.action).where(
                AuditEvent.tenant_id == prompt_context.system_admin.tenant_id,
                AuditEvent.resource_type == "agent_prompt_template",
            )
        )
    )
    assert "AGENT_PROMPT_PUBLISHED" in actions


def test_only_system_admin_can_access_matrix(
    client: TestClient, prompt_context: PromptContext
) -> None:
    # No auth -> 401
    assert client.get("/api/v1/admin/agent-prompts/orchestrator").status_code == 401
    # Course admin (an admin role but not System Admin) -> 403
    assert (
        client.get(
            "/api/v1/admin/agent-prompts/orchestrator",
            headers=_headers(prompt_context.course_token),
        ).status_code
        == 403
    )
    # Student -> 403
    assert (
        client.get(
            "/api/v1/admin/agent-prompts/orchestrator",
            headers=_headers(prompt_context.student_token),
        ).status_code
        == 403
    )
    # System admin -> 200 (no published version yet -> null body)
    assert (
        client.get(
            "/api/v1/admin/agent-prompts/orchestrator",
            headers=_headers(prompt_context.system_token),
        ).status_code
        == 200
    )


def test_create_requires_idempotency_key_and_rejects_unknown_node(
    client: TestClient, prompt_context: PromptContext
) -> None:
    missing_key = client.post(
        "/api/v1/admin/agent-prompts/orchestrator",
        json={"system_prompt": "body"},
        headers=_headers(prompt_context.system_token),
    )
    assert missing_key.status_code == 422

    unknown_node = client.post(
        "/api/v1/admin/agent-prompts/not-a-node",
        json={"system_prompt": "body"},
        headers={**_headers(prompt_context.system_token), "Idempotency-Key": str(uuid4())},
    )
    assert unknown_node.status_code == 422


def test_publish_unknown_version_returns_404(
    client: TestClient, prompt_context: PromptContext
) -> None:
    response = client.post(
        "/api/v1/admin/agent-prompts/orchestrator/999/publish",
        headers=_headers(prompt_context.system_token),
    )
    assert response.status_code == 404


def test_dry_run_returns_contract_with_worker_pending_note(
    client: TestClient, prompt_context: PromptContext
) -> None:
    _create_version(client, prompt_context, "coach", prompt="coach body")
    response = client.post(
        "/api/v1/admin/agent-prompts/coach/dry-run",
        json={"system_prompt": "draft coach body", "sample_input": {"kind": "coaching_feedback"}},
        headers={**_headers(prompt_context.system_token), "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["node"] == "coach"
    assert body["implemented"] is False
    assert "Worker integration pending" in body["note"]


@pytest.mark.parametrize("node", NODES)
def test_every_node_round_trips_through_create_and_current(
    client: TestClient, prompt_context: PromptContext, node: str
) -> None:
    created = _create_version(client, prompt_context, node, prompt=f"{node} body")
    publish = client.post(
        f"/api/v1/admin/agent-prompts/{node}/{created['version']}/publish",
        headers=_headers(prompt_context.system_token),
    )
    assert publish.status_code == 200
    current = client.get(
        f"/api/v1/admin/agent-prompts/{node}", headers=_headers(prompt_context.system_token)
    )
    assert current.status_code == 200
    assert current.json()["node"] == node
    assert current.json()["system_prompt"] == f"{node} body"
