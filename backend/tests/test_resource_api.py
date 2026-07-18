"""BE-007 authenticated, idempotent resource-job API tests."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import create_app
from app.models import KnowledgeNode, OutboxEvent, ResourceJobRecord, User, UserStatus
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant

COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")
NODE_ID = UUID("9512e5ec-f547-51b3-b0df-c5b3a877da9e")
OTHER_NODE_ID = UUID("666b57e9-813f-5eaa-a3dc-4f2a1b19a7d9")


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _student(client: TestClient, db: Session) -> tuple[User, str]:
    tenant = get_or_create_tenant(db, slug="default", name="Default Tenant")
    password = "ValidPass1!"
    user = create_student_user(
        db,
        tenant_id=tenant.id,
        email=f"resource-{uuid4().hex}@example.com",
        password_hash=hash_password(password),
    )
    user.status = UserStatus.ACTIVE
    db.flush()
    response = client.post("/api/v1/auth/login", json={"email": user.email, "password": password})
    assert response.status_code == 200
    return user, response.json()["access_token"]


def _headers(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _payload(node_id: UUID = NODE_ID) -> dict[str, object]:
    return {
        "course_id": str(COURSE_ID),
        "node_id": str(node_id),
        "resource_types": ["STRUCTURE_CARD", "MICRO_LECTURE"],
    }


def test_create_resource_job_derives_sources_writes_outbox_and_replays(
    client: TestClient, db_session: Session
) -> None:
    user, token = _student(client, db_session)
    headers = _headers(token, "resource-create-1")

    first = client.post("/api/v1/resource-jobs", json=_payload(), headers=headers)
    replay = client.post("/api/v1/resource-jobs", json=_payload(), headers=headers)

    assert first.status_code == 202, first.text
    assert replay.status_code == 202
    assert replay.json() == first.json()
    body = first.json()
    assert body["status"] == "QUEUED"
    assert body["progress_percent"] == 0
    assert body["requested_types"] == ["STRUCTURE_CARD", "MICRO_LECTURE"]
    assert "source_ids" not in body

    jobs = list(
        db_session.scalars(
            select(ResourceJobRecord).where(ResourceJobRecord.tenant_id == user.tenant_id)
            .where(ResourceJobRecord.idempotency_key == "resource-create-1")
        )
    )
    assert len(jobs) == 1
    node = db_session.get(KnowledgeNode, NODE_ID)
    assert node is not None
    assert jobs[0].student_id == user.id
    assert jobs[0].source_ids == node.source_ids
    assert len(jobs[0].context_digest) == 64
    event = db_session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.aggregate_type == "resource_job",
            OutboxEvent.aggregate_id == str(jobs[0].id),
        )
    )
    assert event is not None
    assert event.event_type == "RESOURCE_JOB_QUEUED"
    assert event.payload["source_ids"] == node.source_ids


def test_same_idempotency_key_with_different_request_is_conflict(
    client: TestClient, db_session: Session
) -> None:
    _user, token = _student(client, db_session)
    headers = _headers(token, "resource-create-conflict")
    assert client.post("/api/v1/resource-jobs", json=_payload(), headers=headers).status_code == 202

    response = client.post(
        "/api/v1/resource-jobs",
        json=_payload(OTHER_NODE_ID),
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


def test_get_resource_job_is_student_scoped(client: TestClient, db_session: Session) -> None:
    _owner, owner_token = _student(client, db_session)
    created = client.post(
        "/api/v1/resource-jobs",
        json=_payload(),
        headers=_headers(owner_token, "resource-create-scope"),
    )
    job_id = created.json()["id"]
    assert client.get(
        f"/api/v1/resource-jobs/{job_id}", headers=_headers(owner_token)
    ).status_code == 200

    _other, other_token = _student(client, db_session)
    hidden = client.get(f"/api/v1/resource-jobs/{job_id}", headers=_headers(other_token))
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "NOT_FOUND"


def test_create_requires_idempotency_and_governed_node(
    client: TestClient, db_session: Session
) -> None:
    _user, token = _student(client, db_session)

    missing_key = client.post(
        "/api/v1/resource-jobs", json=_payload(), headers=_headers(token)
    )
    unknown_node = client.post(
        "/api/v1/resource-jobs",
        json=_payload(UUID("99999999-9999-4999-8999-999999999999")),
        headers=_headers(token, "resource-create-unknown"),
    )

    assert missing_key.status_code == 422
    assert unknown_node.status_code == 404
    assert unknown_node.json()["code"] == "NOT_FOUND"
