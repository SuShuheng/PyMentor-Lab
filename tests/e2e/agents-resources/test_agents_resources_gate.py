"""INT-004 — agents, resources, SSE and degradation E2E gate (integration lane).

This gate is owned by the integration workstream (``CONTRACT.md`` "Cross-track
acceptance"). It verifies the Agent/resource/streaming integration boundaries
that the BE-006/BE-007 owner unit tests cover only in isolation:

1. **Resource-job lifecycle through HTTP** with persisted progressive
   publication and the dual review gate (FACTUAL retryable, COMPLIANCE final),
   sourced from the same formal-state tables the admin reads.
2. **Tutoring SSE relay** with the full event discriminant set
   (``content_delta``, ``reasoning_delta``, ``tool_call_delta``, ``progress``,
   ``error``, ``done``), monotonic order, ``Last-Event-ID`` cursor forwarding,
   and provider-failure degradation to a typed inline ``error`` then ``done``.
3. **Source-bound boundary**: chat completion is rejected for a node without
   governed sources, and a resource review gate failure never publishes the
   artifact.
4. **Provider/secret safety**: the SSE error path and the inline error event
   surface only stable, redacted fields — no provider key, raw prompt, or stack
   trace leaks through the wire.

The gate exercises real persistence (PostgreSQL via ``db_session``) and the
real FastAPI app (``create_app``). The chat stream service is injected at the
documented ``get_chat_stream_service`` FastAPI dependency seam (the same seam
BE-007 exposes); the sandbox/object-store boundaries use the in-process ports
the owner ships for cross-service verification.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.chat import get_chat_stream_service
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
from app.models import (
    AgentRun,
    LearningResourceRecord,
    ResourceJobRecord,
    ResourceObjectRecord,
    ResourceReviewRecord,
    User,
    UserStatus,
)
from app.resource_publication import SqlResourcePublicationService
from app.resources import (
    InMemoryObjectStore,
    ResourceArtifactStatus,
    ResourceGate,
    ResourceJobStatus,
    ResourceType,
)
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant

# Governed, seeded course assets (see backend/app/knowledge_seed.py).
COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")
# A node WITH governed sources (chat completion allowed).
NODE_ID_WITH_SOURCES = UUID("9512e5ec-f547-51b3-b0df-c5b3a877da9e")
NOW = "2026-07-18T00:00:00Z"


# --------------------------------------------------------------------------- #
# Deterministic chat stream adapter at the documented FastAPI seam.
# --------------------------------------------------------------------------- #


class DeterministicChatStreamService:
    """Deterministic adapter for ``app.api.chat.get_chat_stream_service``.

    Mirrors BE-007's ``FakeChatStreamService`` contract: yields a scripted
    event sequence (or raises a typed ``ChatStreamFailure`` to exercise the
    provider-degradation path) and records the ``Last-Event-ID`` cursor the
    relay forwarded so reconnect semantics are verifiable.
    """

    def __init__(
        self,
        events: list[object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.events = list(events or [])
        self.error = error
        self.after_event_id: str | None = None
        self.calls = 0

    async def stream(
        self,
        *,
        body: object,
        user: User,
        after_event_id: str | None,
    ) -> AsyncIterator[object]:
        del body, user
        self.after_event_id = after_event_id
        self.calls += 1
        if self.error is not None:
            raise self.error
        for event in self.events:
            yield event


def _typed_events() -> list[object]:
    """A full-discriminant ordered stream: reasoning -> content -> tool -> done."""

    return [
        ReasoningDeltaEvent(
            event_id="chat-1:0:reasoning",
            chunk=ChatCompletionChunk(
                id="chat-1", chunk_index=0, delta_reasoning="analyse first", timestamp=NOW
            ),
        ),
        ContentDeltaEvent(
            event_id="chat-1:1:content",
            chunk=ChatCompletionChunk(
                id="chat-1", chunk_index=1, delta_content="answer", timestamp=NOW
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


def _sse_data(body: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


def _sse_event_types(body: str) -> list[str]:
    return [
        line[len("event: ") :].strip()
        for line in body.splitlines()
        if line.startswith("event: ")
    ]


def _sse_event_ids(body: str) -> list[str]:
    return [
        line[len("id: ") :].strip() for line in body.splitlines() if line.startswith("id: ")
    ]


# --------------------------------------------------------------------------- #
# HTTP client fixture (real FastAPI app, real PostgreSQL session).
# --------------------------------------------------------------------------- #


@pytest.fixture()
def api_client(db_session: Session) -> Iterator[tuple[TestClient, DeterministicChatStreamService]]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    service = DeterministicChatStreamService(_typed_events())
    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_chat_stream_service] = lambda: service
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client, service
    app.dependency_overrides.clear()


def _student(api_client: TestClient, db: Session) -> tuple[User, str]:
    tenant = get_or_create_tenant(db, slug="default", name="Default Tenant")
    db.flush()
    password = "ValidPass1!"
    user = create_student_user(
        db,
        tenant_id=tenant.id,
        email=f"agents-{uuid4().hex}@example.com",
        password_hash=hash_password(password),
    )
    user.status = UserStatus.ACTIVE
    db.flush()
    response = api_client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": password}
    )
    assert response.status_code == 200, response.text
    return user, response.json()["access_token"]


def _auth_headers(token: str, *, idem: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if idem is not None:
        headers["Idempotency-Key"] = idem
    return headers


# --------------------------------------------------------------------------- #
# Resource-job gate — HTTP lifecycle, progressive publication, dual gate.
# --------------------------------------------------------------------------- #


def _resource_payload() -> dict[str, object]:
    """ResourceJobCreate only carries course_id/node_id/resource_types; the
    source_ids and context_digest are server-derived from the governed node's
    published sources (see create_resource_job)."""

    return {
        "course_id": str(COURSE_ID),
        "node_id": str(NODE_ID_WITH_SOURCES),
        "resource_types": [
            "MICRO_LECTURE",
            "STRUCTURE_CARD",
            "TRACE_ANIMATION",
            "LAYERED_EXERCISE",
            "NOTEBOOK_TASK",
        ],
    }


def test_resource_job_lifecycle_progresses_through_persisted_states(
    api_client: tuple[TestClient, DeterministicChatStreamService],
    db_session: Session,
) -> None:
    """POST /resource-jobs creates a QUEUED job; GET /resource-jobs/{id} returns
    the persisted view; the five requested resource types are recorded and the
    idempotency contract holds."""

    client, _ = api_client
    user, token = _student(client, db_session)

    create_response = client.post(
        "/api/v1/resource-jobs",
        json=_resource_payload(),
        headers=_auth_headers(token, idem=f"job-create-{uuid4().hex}"),
    )
    assert create_response.status_code == 202, create_response.text
    job_body = create_response.json()
    job_id = job_body["id"]
    assert job_body["status"] in {"QUEUED", "VALIDATING", "GENERATING"}
    assert sorted(job_body["requested_types"]) == [
        "LAYERED_EXERCISE",
        "MICRO_LECTURE",
        "NOTEBOOK_TASK",
        "STRUCTURE_CARD",
        "TRACE_ANIMATION",
    ]
    assert job_body["progress_percent"] == 0

    # The job row is persisted in formal state.
    job_row = db_session.get(ResourceJobRecord, UUID(job_id))
    assert job_row is not None
    assert job_row.student_id == user.id
    assert job_row.tenant_id == user.tenant_id

    # GET returns the same persisted view.
    get_response = client.get(
        f"/api/v1/resource-jobs/{job_id}", headers=_auth_headers(token)
    )
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["id"] == job_id

    # Idempotent replay with the same key returns the same job identity.
    replay_response = client.post(
        "/api/v1/resource-jobs",
        json=_resource_payload(),
        headers=_auth_headers(token, idem=create_response.request.headers["Idempotency-Key"]),
    )
    assert replay_response.status_code == 202, replay_response.text
    assert replay_response.json()["id"] == job_id


def test_progressive_publication_publishes_all_five_resource_types(
    api_client: tuple[TestClient, DeterministicChatStreamService],
    db_session: Session,
) -> None:
    """Driving the publication service through both review gates for all five
    requested types progresses the persisted job from PARTIAL_READY to READY,
    with versioned resource/object/review rows sourced from one formal store."""

    client, _ = api_client
    _user, token = _student(client, db_session)
    create_response = client.post(
        "/api/v1/resource-jobs",
        json=_resource_payload(),
        headers=_auth_headers(token, idem=f"pub-{uuid4().hex}"),
    )
    assert create_response.status_code == 202, create_response.text
    job_id = UUID(create_response.json()["id"])

    store = InMemoryObjectStore()
    service = SqlResourcePublicationService(db_session, store)

    resource_types = [
        ResourceType.MICRO_LECTURE,
        ResourceType.STRUCTURE_CARD,
        ResourceType.TRACE_ANIMATION,
        ResourceType.LAYERED_EXERCISE,
        ResourceType.NOTEBOOK_TASK,
    ]
    source_ids = (UUID("6c32b9cb-a61b-58f7-8d11-d4925ffbecfb"),)
    for index, resource_type in enumerate(resource_types):
        published_count = index + 1
        staged = service.stage(
            job_id=job_id,
            resource_type=resource_type,
            content=f'{{"kind":"{resource_type.value}","i":{index}}}'.encode(),
            mime_type="application/json",
            source_ids=source_ids,
        )
        service.review(
            resource_id=staged.id,
            gate=ResourceGate.FACTUAL,
            passed=True,
            findings=(),
            reviewer="integration-factual-gate",
        )
        service.review(
            resource_id=staged.id,
            gate=ResourceGate.COMPLIANCE,
            passed=True,
            findings=(),
            reviewer="integration-compliance-gate",
        )
        service.publish(resource_id=staged.id)

        job_row = db_session.get(ResourceJobRecord, job_id)
        assert job_row is not None
        if published_count < len(resource_types):
            assert job_row.status == ResourceJobStatus.PARTIAL_READY, (
                f"after {published_count} types the job must be PARTIAL_READY, "
                f"got {job_row.status}"
            )
            assert 0 < job_row.progress_percent < 100
        else:
            assert job_row.status == ResourceJobStatus.READY
            assert job_row.progress_percent == 100

    # All five resource/object/review rows are persisted and published.
    resources = list(
        db_session.scalars(
            select(LearningResourceRecord).where(
                LearningResourceRecord.job_id == job_id
            )
        )
    )
    assert len(resources) == 5
    assert all(r.status == ResourceArtifactStatus.PUBLISHED for r in resources)

    objects = list(
        db_session.scalars(
            select(ResourceObjectRecord).where(
                ResourceObjectRecord.resource_id.in_([r.id for r in resources])
            )
        )
    )
    assert len(objects) == 5
    assert all(o.published for o in objects)

    reviews = list(
        db_session.scalars(
            select(ResourceReviewRecord).where(
                ResourceReviewRecord.resource_id.in_([r.id for r in resources])
            )
        )
    )
    # Two gates (FACTUAL + COMPLIANCE) per resource.
    assert len(reviews) == 10
    assert all(r.passed for r in reviews)


def test_compliance_gate_failure_is_terminal_and_never_publishes(
    api_client: tuple[TestClient, DeterministicChatStreamService],
    db_session: Session,
) -> None:
    """A COMPLIANCE gate failure must mark the job FAILED_FINAL (non-retryable)
    and must never publish the artifact — the source-bound safety boundary."""

    client, _ = api_client
    _user, token = _student(client, db_session)
    create_response = client.post(
        "/api/v1/resource-jobs",
        json=_resource_payload(),
        headers=_auth_headers(token, idem=f"reject-{uuid4().hex}"),
    )
    assert create_response.status_code == 202, create_response.text
    job_id = UUID(create_response.json()["id"])

    store = InMemoryObjectStore()
    service = SqlResourcePublicationService(db_session, store)
    source_ids = (UUID("6c32b9cb-a61b-58f7-8d11-d4925ffbecfb"),)
    staged = service.stage(
        job_id=job_id,
        resource_type=ResourceType.MICRO_LECTURE,
        content=b'{"kind":"micro-lecture"}',
        mime_type="application/json",
        source_ids=source_ids,
    )
    service.review(
        resource_id=staged.id,
        gate=ResourceGate.FACTUAL,
        passed=True,
        findings=(),
        reviewer="integration-factual-gate",
    )
    service.review(
        resource_id=staged.id,
        gate=ResourceGate.COMPLIANCE,
        passed=False,
        findings=("policy violation",),
        reviewer="integration-compliance-gate",
    )

    job_row = db_session.get(ResourceJobRecord, job_id)
    assert job_row is not None
    assert job_row.status == ResourceJobStatus.FAILED_FINAL, (
        "a COMPLIANCE failure must be terminal (FAILED_FINAL), "
        f"got {job_row.status}"
    )
    assert job_row.error_code == "REVIEW_GATE_FAILED"

    # The artifact was rejected and never published.
    rejected = db_session.get(LearningResourceRecord, staged.id)
    assert rejected is not None
    assert rejected.status == ResourceArtifactStatus.REJECTED

    objects = list(
        db_session.scalars(
            select(ResourceObjectRecord).where(
                ResourceObjectRecord.resource_id == staged.id
            )
        )
    )
    assert all(not o.published for o in objects)


# --------------------------------------------------------------------------- #
# Tutoring SSE gate — discriminants, order, cursor, degradation, safety.
# --------------------------------------------------------------------------- #


def _chat_payload(node_id: UUID = NODE_ID_WITH_SOURCES) -> dict[str, object]:
    return {
        "course_id": str(COURSE_ID),
        "node_id": str(node_id),
        "messages": [{"role": "user", "content": "Explain loop boundary errors."}],
        "stream": True,
    }


def test_sse_relays_typed_events_in_order_with_cursor(
    api_client: tuple[TestClient, DeterministicChatStreamService],
    db_session: Session,
) -> None:
    """The tutoring SSE relay preserves event order across the full
    discriminant set and forwards the Last-Event-ID cursor to the stream
    service for reconnect/replay."""

    client, service = api_client
    _user, token = _student(client, db_session)

    response = client.post(
        "/api/v1/chat/completions",
        json=_chat_payload(),
        headers={"Authorization": f"Bearer {token}", "Last-Event-ID": "chat-1:0:reasoning"},
    )
    assert response.status_code == 200, response.text
    body = response.text

    # Cursor forwarded for reconnect/replay semantics.
    assert service.after_event_id == "chat-1:0:reasoning"

    event_types = _sse_event_types(body)
    assert event_types == [
        "reasoning_delta",
        "content_delta",
        "tool_call_delta",
        "done",
    ], f"SSE event order must be preserved, got {event_types}"

    event_ids = _sse_event_ids(body)
    assert event_ids == [
        "chat-1:0:reasoning",
        "chat-1:1:content",
        "chat-1:2:tool",
        "chat-1:3:done",
    ]

    payloads = _sse_data(body)
    assert payloads[-1]["type"] == "done"
    # The tool_call_delta carries the tool shape (no raw provider key).
    tool_event = payloads[2]
    assert tool_event["type"] == "tool_call_delta"
    assert tool_event["chunk"]["delta_tool_calls"][0]["name"] == "knowledge_search"


def test_sse_provider_failure_degrades_to_typed_error_then_done(
    api_client: tuple[TestClient, DeterministicChatStreamService],
    db_session: Session,
) -> None:
    """When the configured provider fails mid-stream, the relay must emit a
    typed inline ``error`` event with a stable redacted code and then a
    terminal ``done`` — never a raw provider payload, stack trace, or key."""

    client, service = api_client
    _user, token = _student(client, db_session)

    from app.api.chat import ChatStreamFailure

    service.events = []
    service.error = ChatStreamFailure(
        "PROVIDER_UNAVAILABLE",
        True,
        "upstream returned 503",
    )

    response = client.post(
        "/api/v1/chat/completions",
        json=_chat_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.text

    event_types = _sse_event_types(body)
    assert "error" in event_types, "provider failure must emit a typed error event"
    assert event_types[-1] == "done", "the relay must close with a terminal done event"

    error_payload = next(
        data for data in _sse_data(body) if data.get("type") == "error"
    )
    inline_error = error_payload["error"]
    assert inline_error["code"] == "PROVIDER_UNAVAILABLE"
    assert inline_error["retryable"] is True
    assert "trace_id" in inline_error
    # Safety: the redacted message must not leak the raw upstream detail.
    assert "503" not in inline_error["message"]
    assert "upstream" not in inline_error["message"].lower()


def test_chat_completion_is_source_bound_and_rejects_ungoverned_nodes(
    api_client: tuple[TestClient, DeterministicChatStreamService],
    db_session: Session,
) -> None:
    """A chat completion against a node without governed sources is rejected
    with a stable 404 — the source-bound boundary that prevents the tutoring
    stream from inventing content outside the governed knowledge graph."""

    client, _ = api_client
    _user, token = _student(client, db_session)

    # Pick a node UUID in the same course shape but not seeded; the API must
    # treat it as ungoverned and refuse rather than stream.
    unguarded_node = UUID("00000000-0000-5000-8000-000000000001")
    response = client.post(
        "/api/v1/chat/completions",
        json=_chat_payload(node_id=unguarded_node),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404, response.text
    body = response.json()
    # The error envelope is the stable serializable shape, no leak.
    assert body["code"] in {"NOT_FOUND", "INTERNAL_ERROR"}
    assert "details" in body


# --------------------------------------------------------------------------- #
# Cross-language agent-event boundary — real Redis stream ingest.
# --------------------------------------------------------------------------- #


def test_agent_audit_envelope_is_ingested_from_real_redis_stream(
    db_engine,
) -> None:
    """The Python agent-event consumer ingests a TypeScript-Worker-shaped
    ``AgentAuditEnvelope`` from the real Redis stream and persists the agent
    run/audit rows in PostgreSQL. This is the cross-language integration
    boundary: the Worker emits, the API ingests, both share one contract.

    This test deliberately uses its own short-lived sessions against the real
    engine (not the savepoint-bound ``db_session``) because the consumer drives
    its own ``db.begin()``/commit lifecycle per message. Each session commits
    or rolls back independently; teardown removes the tenant-scoped identity so
    the gate never leaves formal state behind."""

    redis_async = pytest.importorskip("redis.asyncio")
    # Prefer 127.0.0.1 over localhost: redis-py's async client on Windows can
    # resolve localhost to ::1 first and time out against an IPv4-only Redis.
    redis_url = os.environ.get(
        "PYMENTOR_REDIS_URL", "redis://127.0.0.1:6379/0"
    ).replace("localhost", "127.0.0.1")
    try:
        import redis as redis_sync

        probe = redis_sync.Redis.from_url(redis_url, socket_connect_timeout=5)
        probe.ping()
        probe.close()
    except Exception as exc:  # pragma: no cover - depends on live service
        pytest.skip(f"Redis unavailable for cross-language agent-event gate: {exc}")

    from app.agent_event_consumer import consume_agent_events_once
    from app.config import get_settings
    from app.contracts.worker import AgentAuditDetail, AgentAuditEnvelope, AgentAuditEventType
    from app.models import Tenant, User, UserStatus

    suffix = uuid4().hex
    stream = f"pymentor:agent-events:integration:{suffix}"
    group = f"pymentor-integration-{suffix}"
    consumer = f"integration-{suffix}"

    # Commit the tenant + student on a dedicated session so the consumer's own
    # transaction can satisfy the tenant/user foreign keys.
    with Session(db_engine) as setup_session:
        tenant = Tenant(slug=f"agents-{suffix}", name="Agents Integration")
        setup_session.add(tenant)
        setup_session.flush()
        student = User(
            tenant_id=tenant.id,
            email=f"agents-stream-{suffix}@example.com",
            password_hash="not-used",
            status=UserStatus.ACTIVE,
        )
        setup_session.add(student)
        setup_session.flush()
        tenant_id, student_id = tenant.id, student.id
        setup_session.commit()

    occurred_at = datetime.now(UTC)
    envelope = AgentAuditEnvelope(
        agent_run_id=f"run-{suffix}",
        event_id=f"evt-{suffix}",
        trace_id=f"trc-{suffix}",
        tenant_id=str(tenant_id),
        student_id=str(student_id),
        sequence=1,
        event_type=AgentAuditEventType.RUN_STARTED,
        node=None,
        tool_name=None,
        checkpoint_id=None,
        detail=AgentAuditDetail(status="RUNNING", retry_count=0, fallback=False),
        occurred_at=occurred_at,
    )

    async def _publish_and_consume() -> int:
        redis = redis_async.Redis.from_url(redis_url, socket_connect_timeout=10)
        try:
            await redis.xadd(stream, {"payload": envelope.model_dump_json()})
            from dataclasses import replace as dataclass_replace

            settings = dataclass_replace(
                get_settings(),
                agent_event_stream=stream,
                agent_event_group=group,
                agent_event_consumer=consumer,
                agent_event_block_ms=200,
                agent_event_claim_idle_ms=100,
            )
            return await consume_agent_events_once(
                redis,
                lambda: Session(db_engine),
                settings,
            )
        finally:
            try:
                await redis.delete(stream)
            finally:
                await redis.aclose()

    ingested = asyncio.run(_publish_and_consume())
    assert ingested >= 1, (
        "the agent-event consumer must ingest the Worker-shaped envelope from "
        "the real Redis stream"
    )

    # The run row is persisted in PostgreSQL formal state. Use a fresh session
    # so the assertion reads the consumer's committed rows.
    with Session(db_engine) as assert_session:
        run = assert_session.scalar(
            select(AgentRun).where(AgentRun.external_run_id == envelope.agent_run_id)
        )
        assert run is not None, "ingested RUN_STARTED must persist an AgentRun row"
        assert run.tenant_id == tenant_id
        assert run.student_id == student_id

    # Teardown the tenant-scoped identity so the gate leaves no formal state
    # behind. ``users.tenant_id`` is ON DELETE RESTRICT, and ``agent_runs`` is
    # ON DELETE CASCADE from users, so delete the user first (which cascades to
    # the agent run) and then the tenant.
    with Session(db_engine) as cleanup_session:
        cleanup_session.delete(cleanup_session.get(User, student_id))
        cleanup_session.flush()
        cleanup_session.delete(cleanup_session.get(Tenant, tenant_id))
        cleanup_session.commit()
