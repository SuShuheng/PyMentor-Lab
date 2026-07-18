"""BE-007 authenticated SSE relay and reconnect tests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.chat import ChatStreamFailure, get_chat_stream_service
from app.contracts.streaming import (
    ChatCompletionChunk,
    ContentDeltaEvent,
    DoneEvent,
    ReasoningDeltaEvent,
    ToolCallDelta,
    ToolCallDeltaEvent,
)
from app.db import get_db
from app.main import create_app
from app.models import User, UserStatus
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant

COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")
NODE_ID = UUID("9512e5ec-f547-51b3-b0df-c5b3a877da9e")
NOW = "2026-07-18T00:00:00Z"


class FakeChatStreamService:
    def __init__(self, events: list[object] | None = None, error: Exception | None = None) -> None:
        self.events = events or []
        self.error = error
        self.after_event_id: str | None = None

    async def stream(self, *, body: object, user: User, after_event_id: str | None):
        del body, user
        self.after_event_id = after_event_id
        if self.error is not None:
            raise self.error
        for event in self.events:
            yield event


@pytest.fixture()
def client_factory(db_session: Session):
    clients: list[TestClient] = []

    def _factory(service: FakeChatStreamService) -> TestClient:
        def _override_get_db() -> Iterator[Session]:
            yield db_session

        app = create_app()
        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_chat_stream_service] = lambda: service
        client = TestClient(app, raise_server_exceptions=False)
        clients.append(client)
        return client

    yield _factory
    for client in clients:
        client.close()


def _student(client: TestClient, db: Session) -> str:
    tenant = get_or_create_tenant(db, slug="default", name="Default Tenant")
    password = "ValidPass1!"
    user = create_student_user(
        db,
        tenant_id=tenant.id,
        email=f"stream-{uuid4().hex}@example.com",
        password_hash=hash_password(password),
    )
    user.status = UserStatus.ACTIVE
    db.flush()
    response = client.post("/api/v1/auth/login", json={"email": user.email, "password": password})
    return response.json()["access_token"]


def _payload(node_id: UUID = NODE_ID) -> dict[str, object]:
    return {
        "course_id": str(COURSE_ID),
        "node_id": str(node_id),
        "messages": [{"role": "user", "content": "Explain loops."}],
        "stream": True,
    }


def _events() -> list[object]:
    return [
        ReasoningDeltaEvent(
            event_id="chat-1:0:reasoning",
            chunk=ChatCompletionChunk(
                id="chat-1", chunk_index=0, delta_reasoning="先分析", timestamp=NOW
            ),
        ),
        ContentDeltaEvent(
            event_id="chat-1:1:content",
            chunk=ChatCompletionChunk(
                id="chat-1", chunk_index=1, delta_content="答案", timestamp=NOW
            ),
        ),
        ToolCallDeltaEvent(
            event_id="chat-1:2:tool",
            chunk=ChatCompletionChunk(
                id="chat-1",
                chunk_index=2,
                delta_tool_calls=[
                    ToolCallDelta(index=0, id="call-1", name="knowledge_search", arguments="{}")
                ],
                timestamp=NOW,
            ),
        ),
        DoneEvent(event_id="chat-1:3:done"),
    ]


def _data(body: str) -> list[dict[str, object]]:
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


def test_streams_typed_events_in_order_and_forwards_reconnect_cursor(
    client_factory, db_session: Session
) -> None:
    service = FakeChatStreamService(_events())
    client = client_factory(service)
    token = _student(client, db_session)

    response = client.post(
        "/api/v1/chat/completions",
        json=_payload(),
        headers={
            "Authorization": f"Bearer {token}",
            "Last-Event-ID": "chat-1:0:reasoning",
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert service.after_event_id == "chat-1:0:reasoning"
    assert [item["type"] for item in _data(response.text)] == [
        "reasoning_delta",
        "content_delta",
        "tool_call_delta",
        "done",
    ]
    ids = [line[4:] for line in response.text.splitlines() if line.startswith("id: ")]
    assert ids == [event.event_id for event in _events()]


def test_provider_failure_becomes_redacted_error_then_done(
    client_factory, db_session: Session
) -> None:
    service = FakeChatStreamService(
        error=ChatStreamFailure(
            "RATE_LIMITED", True, "upstream secret-provider-key should not escape"
        )
    )
    client = client_factory(service)
    token = _student(client, db_session)

    response = client.post(
        "/api/v1/chat/completions",
        json=_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    events = _data(response.text)
    assert [event["type"] for event in events] == ["error", "done"]
    assert events[0]["error"]["code"] == "RATE_LIMITED"
    assert events[0]["error"]["retryable"] is True
    assert "secret-provider-key" not in response.text


def test_rejects_unknown_or_source_free_node_before_opening_stream(
    client_factory, db_session: Session
) -> None:
    service = FakeChatStreamService(_events())
    client = client_factory(service)
    token = _student(client, db_session)

    response = client.post(
        "/api/v1/chat/completions",
        json=_payload(UUID("99999999-9999-4999-8999-999999999999")),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
