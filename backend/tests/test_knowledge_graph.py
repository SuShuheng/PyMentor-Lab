"""Knowledge graph edges query API tests (BE-021)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import create_app
from app.mastery import AssessmentFacts, MasteryPolicy, record_assessment_and_decide
from app.models import MasteryState, User, UserStatus
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant

COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")
NODE_ID = UUID("9512e5ec-f547-51b3-b0df-c5b3a877da9e")
NOW = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
POLICY = MasteryPolicy(
    independence_min=0.7,
    transfer_min=0.6,
    max_hints_for_mastery=1,
    review_delay_days=7,
)


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def student_auth(client: TestClient, db_session: Session) -> tuple[User, str]:
    tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
    db_session.flush()
    password = "ValidPass1!"
    user = create_student_user(
        db_session,
        tenant_id=tenant.id,
        email=f"graph-{uuid4_hex()}@example.com",
        password_hash=hash_password(password),
    )
    user.status = UserStatus.ACTIVE
    db_session.flush()
    response = client.post("/api/v1/auth/login", json={"email": user.email, "password": password})
    assert response.status_code == 200, response.text
    return user, response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def uuid4_hex() -> str:
    from uuid import uuid4

    return uuid4().hex


def _grant_mastery(db_session: Session, user: User) -> MasteryState:
    """Drive a node to INITIAL_MASTERY for the requesting student so the graph
    left-join surfaces a non-null mastery status for that node."""
    record_assessment_and_decide(
        db_session,
        AssessmentFacts(
            correct=True,
            hidden_tests_passed=True,
            hints_used=0,
            support_level=0,
            independence_score=0.9,
            transfer_score=0.8,
            platform_error=False,
        ),
        policy=POLICY,
        tenant_id=user.tenant_id,
        student_id=user.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        evidence_event_id=f"evt_graph_{uuid4_hex()}",
        now=NOW,
    )
    state = db_session.scalar(
        select(MasteryState).where(
            MasteryState.student_id == user.id,
            MasteryState.node_id == NODE_ID,
        )
    )
    assert state is not None
    return state


def test_graph_requires_authentication(client: TestClient) -> None:
    """No Authorization header → 401 (BE-021 auth gate)."""
    response = client.get("/api/v1/knowledge/graph")
    assert response.status_code == 401


def test_graph_returns_nodes_edges_and_mastery(
    client: TestClient, db_session: Session, student_auth
) -> None:
    student, token = student_auth
    state = _grant_mastery(db_session, student)

    response = client.get("/api/v1/knowledge/graph", headers=_headers(token))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["course_id"] == str(COURSE_ID)

    # Canonical course exposes 14 chapters / 93 nodes.
    nodes = payload["nodes"]
    assert len(nodes) >= 90
    node_ids = {node["node_id"] for node in nodes}
    assert str(NODE_ID) in node_ids

    # Edges come from the per-node prerequisites JSON column.
    edges = payload["edges"]
    assert len(edges) >= 1
    for edge in edges:
        assert edge["kind"] == "prerequisite"
        assert edge["from_node_id"] in node_ids
        assert edge["to_node_id"] in node_ids

    # Per-node mastery join: the node we advanced must carry the recorded status,
    # and at least one other node must surface as unseen (null mastery_status).
    mastered = next(node for node in nodes if node["node_id"] == str(NODE_ID))
    assert mastered["mastery_status"] == state.status.value

    unseen = [node for node in nodes if node["mastery_status"] is None]
    assert len(unseen) >= 1


def test_graph_filters_by_course_id(client: TestClient, db_session: Session, student_auth) -> None:
    _, token = student_auth
    response = client.get(f"/api/v1/knowledge/graph?course_id={COURSE_ID}", headers=_headers(token))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["course_id"] == str(COURSE_ID)
    assert len(payload["nodes"]) >= 90


def test_graph_is_deterministic_across_calls(
    client: TestClient, db_session: Session, student_auth
) -> None:
    _, token = student_auth
    first = client.get("/api/v1/knowledge/graph", headers=_headers(token)).json()
    second = client.get("/api/v1/knowledge/graph", headers=_headers(token)).json()
    assert first == second
