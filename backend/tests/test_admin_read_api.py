"""BE-010 tenant-scoped, paginated administrative read API tests."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import create_app
from app.models import (
    AgentRun,
    AgentToolCall,
    EvidenceEvent,
    KnowledgeNode,
    LearningPath,
    LearningPathStatus,
    LearningPathStep,
    LearningResourceRecord,
    MasteryState,
    MasteryStatus,
    PathStepKind,
    PathValidationStatus,
    ProfileDimension,
    ProfileDimensionScore,
    ProfileVersion,
    ResourceJobRecord,
    ResourceReviewRecord,
    ReviewSchedule,
    ReviewStatus,
    RoleName,
    TaskDefinition,
    TaskInstance,
    TaskInstanceStatus,
    TaskVersion,
    Tenant,
    User,
    UserStatus,
)
from app.observability import record_provider_call
from app.providers import ProviderType
from app.resources import (
    ResourceArtifactStatus,
    ResourceGate,
    ResourceJobStatus,
    ResourceType,
)
from app.security import hash_password
from app.services import assign_role, create_student_user, get_or_create_tenant

COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")
NODE_ID = UUID("9512e5ec-f547-51b3-b0df-c5b3a877da9e")
NOW = datetime(2026, 7, 18, 6, 0, tzinfo=UTC)


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    access_token = response.json()["access_token"]
    assert isinstance(access_token, str)
    return access_token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_admin(db: Session, *, role: RoleName = RoleName.COURSE_ADMIN) -> User:
    tenant = get_or_create_tenant(db, slug="default", name="Default Tenant")
    admin = User(
        tenant_id=tenant.id,
        email=f"admin-{uuid4().hex}@example.com",
        password_hash=hash_password("AdminPass1!"),
        status=UserStatus.ACTIVE,
        display_name="Course Admin",
    )
    db.add(admin)
    db.flush()
    assign_role(db, user_id=admin.id, role_name=role.value)
    return admin


def _make_student(
    db: Session,
    tenant: Tenant,
    *,
    label: str,
) -> User:
    student = create_student_user(
        db,
        tenant_id=tenant.id,
        email=f"{label}-{uuid4().hex}@example.com",
        password_hash=hash_password("StudentPass1!"),
        student_no=f"S-{uuid4().hex[:10]}",
        display_name=label,
    )
    student.status = UserStatus.ACTIVE
    db.flush()
    return student


@dataclass(slots=True)
class ReadContext:
    tenant: Tenant
    admin: User
    admin_token: str
    search_token: str
    first: User
    second: User
    foreign: User


@pytest.fixture()
def read_context(client: TestClient, db_session: Session) -> ReadContext:
    admin = _make_admin(db_session)
    tenant = db_session.get(Tenant, admin.tenant_id)
    assert tenant is not None
    search_token = f"group-{uuid4().hex}"
    first = _make_student(db_session, tenant, label=f"{search_token}-First")
    second = _make_student(db_session, tenant, label=f"{search_token}-Second")
    foreign_tenant = Tenant(slug=f"foreign-{uuid4().hex}", name="Foreign")
    db_session.add(foreign_tenant)
    db_session.flush()
    foreign = _make_student(db_session, foreign_tenant, label="Foreign")
    token = _login(client, admin.email, "AdminPass1!")
    return ReadContext(tenant, admin, token, search_token, first, second, foreign)


def _seed_learning_rows(db: Session, context: ReadContext) -> None:
    profile = ProfileVersion(
        tenant_id=context.tenant.id,
        student_id=context.first.id,
        version=1,
        source_event_id=f"profile-{uuid4().hex}",
    )
    db.add(profile)
    db.flush()
    db.add(
        ProfileDimensionScore(
            tenant_id=context.tenant.id,
            profile_version_id=profile.id,
            dimension=ProfileDimension.DEBUGGING,
            scope_key="GLOBAL",
            score=0.75,
            confidence=0.8,
            support_level=1,
        )
    )
    path = LearningPath(
        tenant_id=context.tenant.id,
        student_id=context.first.id,
        course_id=COURSE_ID,
        version=1,
        status=LearningPathStatus.CURRENT,
        source_proposal={},
        validation_findings=[],
    )
    db.add(path)
    db.flush()
    db.add(
        LearningPathStep(
            tenant_id=context.tenant.id,
            path_id=path.id,
            position=1,
            node_id=NODE_ID,
            kind=PathStepKind.LEARN,
            estimated_minutes=20,
            scenario_key="admin-read",
            source_metadata={},
            validation_status=PathValidationStatus.VALIDATED,
            validation_outcome={},
        )
    )
    definition = TaskDefinition(
        tenant_id=context.tenant.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        key=f"admin-read-{uuid4().hex}",
        title="Admin read task",
    )
    db.add(definition)
    db.flush()
    task_version = TaskVersion(
        tenant_id=context.tenant.id,
        definition_id=definition.id,
        version=1,
        snapshot={"prompt": "bounded"},
        snapshot_digest="a" * 64,
        scenario_key="admin-read",
        published=True,
        published_at=NOW,
    )
    db.add(task_version)
    db.flush()
    db.add(
        TaskInstance(
            tenant_id=context.tenant.id,
            student_id=context.first.id,
            task_version_id=task_version.id,
            active_key=f"admin-read-{uuid4().hex}",
            status=TaskInstanceStatus.COMPLETED,
            snapshot={"prompt": "bounded"},
            snapshot_digest=task_version.snapshot_digest,
            version=1,
            completed_at=NOW,
        )
    )
    mastery = MasteryState(
        tenant_id=context.tenant.id,
        student_id=context.first.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        status=MasteryStatus.LEARNING,
        version=1,
    )
    db.add(mastery)
    db.flush()
    db.add(
        ReviewSchedule(
            tenant_id=context.tenant.id,
            student_id=context.first.id,
            course_id=COURSE_ID,
            node_id=NODE_ID,
            mastery_state_id=mastery.id,
            scenario_key="admin-read",
            due_at=NOW - timedelta(minutes=5),
            original_due_at=NOW - timedelta(minutes=5),
            hint_ceiling=0,
            status=ReviewStatus.DUE,
            version=1,
        )
    )
    for index in range(2):
        db.add(
            EvidenceEvent(
                tenant_id=context.tenant.id,
                student_id=context.first.id,
                event_id=f"admin-evidence-{index}-{uuid4().hex}",
                event_type="TASK_SUBMITTED",
                course_id=COURSE_ID,
                node_id=NODE_ID,
                trace_id=f"trc_admin_{index}",
                payload={"answer": "must-not-be-returned"},
                evidence_confidence=0.9,
                created_at=NOW + timedelta(seconds=index),
            )
        )
    foreign_mastery = MasteryState(
        tenant_id=context.foreign.tenant_id,
        student_id=context.foreign.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        status=MasteryStatus.STABLE_MASTERY,
        version=1,
    )
    db.add(foreign_mastery)
    db.flush()


def _seed_resource_review(db: Session, context: ReadContext) -> LearningResourceRecord:
    job = ResourceJobRecord(
        tenant_id=context.tenant.id,
        student_id=context.first.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        idempotency_key=f"admin-resource-{uuid4().hex}",
        request_digest="b" * 64,
        status=ResourceJobStatus.REVIEWING,
        requested_types=[ResourceType.STRUCTURE_CARD.value],
        source_ids=["40000000-0000-4000-8000-000000000001"],
        context_digest="c" * 64,
        progress_percent=0,
    )
    db.add(job)
    db.flush()
    resource = LearningResourceRecord(
        tenant_id=context.tenant.id,
        job_id=job.id,
        resource_type=ResourceType.STRUCTURE_CARD,
        version=1,
        status=ResourceArtifactStatus.REVIEWING,
        source_ids=job.source_ids,
        context_digest=job.context_digest,
        content_digest="d" * 64,
        metadata_json={},
    )
    db.add(resource)
    db.flush()
    db.add(
        ResourceReviewRecord(
            resource_id=resource.id,
            gate=ResourceGate.FACTUAL,
            version=1,
            passed=True,
            findings=[],
            reviewer="factual-v1",
        )
    )
    foreign_job = ResourceJobRecord(
        tenant_id=context.foreign.tenant_id,
        student_id=context.foreign.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        idempotency_key=f"foreign-resource-{uuid4().hex}",
        request_digest="e" * 64,
        status=ResourceJobStatus.REVIEWING,
        requested_types=[ResourceType.STRUCTURE_CARD.value],
        source_ids=["40000000-0000-4000-8000-000000000001"],
        context_digest="f" * 64,
        progress_percent=0,
    )
    db.add(foreign_job)
    db.flush()
    db.add(
        LearningResourceRecord(
            tenant_id=context.foreign.tenant_id,
            job_id=foreign_job.id,
            resource_type=ResourceType.STRUCTURE_CARD,
            version=1,
            status=ResourceArtifactStatus.REVIEWING,
            source_ids=foreign_job.source_ids,
            context_digest=foreign_job.context_digest,
            content_digest="1" * 64,
            metadata_json={},
        )
    )
    db.flush()
    return resource


def _seed_agent_run(db: Session, context: ReadContext) -> AgentRun:
    run = AgentRun(
        external_run_id=f"run-{uuid4().hex}",
        event_id=f"event-{uuid4().hex}",
        trace_id=f"trace-{uuid4().hex}",
        tenant_id=context.tenant.id,
        student_id=context.first.id,
        status="SUCCEEDED",
        route="resource",
        latest_sequence=2,
        checkpoint_thread_id=f"thread-{uuid4().hex}",
        latest_checkpoint_id=f"checkpoint-{uuid4().hex}",
        fallback_used=False,
        safe_input_snapshot={"api_key": "super-secret", "summary": "bounded"},
        safe_output_snapshot={"result": "safe"},
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
    )
    db.add(run)
    db.flush()
    db.add(
        AgentToolCall(
            tenant_id=context.tenant.id,
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
            occurred_at=NOW,
        )
    )
    db.flush()
    return run


def test_student_is_denied_admin_student_list(
    client: TestClient, db_session: Session, read_context: ReadContext
) -> None:
    token = _login(client, read_context.first.email, "StudentPass1!")

    response = client.get("/api/v1/admin/students", headers=_headers(token))

    assert response.status_code == 403


def test_reviewer_can_read_resource_reviews_but_not_student_data(
    client: TestClient, db_session: Session, read_context: ReadContext
) -> None:
    reviewer = _make_admin(db_session, role=RoleName.REVIEWER)
    reviewer_token = _login(client, reviewer.email, "AdminPass1!")
    headers = _headers(reviewer_token)

    students = client.get("/api/v1/admin/students", headers=headers)
    reviews = client.get("/api/v1/admin/resources/reviews", headers=headers)

    assert students.status_code == 403
    assert reviews.status_code == 200, reviews.text


def test_student_list_is_tenant_scoped_and_stably_paginated(
    client: TestClient, read_context: ReadContext
) -> None:
    headers = _headers(read_context.admin_token)
    first_page = client.get(
        f"/api/v1/admin/students?page=1&page_size=1&q={read_context.search_token}",
        headers=headers,
    )
    second_page = client.get(
        f"/api/v1/admin/students?page=2&page_size=1&q={read_context.search_token}",
        headers=headers,
    )
    out_of_range = client.get(
        f"/api/v1/admin/students?page=3&page_size=1&q={read_context.search_token}",
        headers=headers,
    )

    assert first_page.status_code == 200, first_page.text
    assert second_page.status_code == 200, second_page.text
    assert out_of_range.status_code == 200
    first_body = first_page.json()
    second_body = second_page.json()
    assert first_body["page"] == {
        "number": 1,
        "size": 1,
        "total_items": 2,
        "total_pages": 2,
    }
    assert second_body["page"]["number"] == 2
    assert out_of_range.json()["items"] == []
    listed = {first_body["items"][0]["id"], second_body["items"][0]["id"]}
    assert listed == {str(read_context.first.id), str(read_context.second.id)}
    assert str(read_context.foreign.id) not in first_page.text + second_page.text
    assert "password" not in first_page.text.lower()


def test_student_profile_progress_and_evidence_are_read_only_and_scoped(
    client: TestClient, db_session: Session, read_context: ReadContext
) -> None:
    _seed_learning_rows(db_session, read_context)
    headers = _headers(read_context.admin_token)

    profile = client.get(f"/api/v1/admin/students/{read_context.first.id}/profile", headers=headers)
    progress = client.get(
        f"/api/v1/admin/students/{read_context.first.id}/progress", headers=headers
    )
    evidence = client.get(
        f"/api/v1/admin/students/{read_context.first.id}/evidence?page=1&page_size=1",
        headers=headers,
    )
    foreign = client.get(
        f"/api/v1/admin/students/{read_context.foreign.id}/progress", headers=headers
    )

    assert profile.status_code == 200, profile.text
    assert profile.json()["version"] == 1
    assert profile.json()["dimensions"][0]["dimension"] == "DEBUGGING"
    assert progress.status_code == 200, progress.text
    assert progress.json()["completed_tasks"] == 1
    assert progress.json()["due_reviews"] == 1
    assert progress.json()["current_node_id"] == str(NODE_ID)
    assert progress.json()["mastery_counts"] == {"LEARNING": 1}
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["page"]["total_items"] == 2
    assert len(evidence.json()["items"]) == 1
    assert "payload" not in evidence.json()["items"][0]
    assert "must-not-be-returned" not in evidence.text
    assert foreign.status_code == 404


def test_mastery_summary_and_resource_reviews_exclude_other_tenants(
    client: TestClient, db_session: Session, read_context: ReadContext
) -> None:
    _seed_learning_rows(db_session, read_context)
    resource = _seed_resource_review(db_session, read_context)
    headers = _headers(read_context.admin_token)

    mastery = client.get(f"/api/v1/admin/mastery/summary?course_id={COURSE_ID}", headers=headers)
    reviews = client.get("/api/v1/admin/resources/reviews?page=1&page_size=20", headers=headers)

    assert mastery.status_code == 200, mastery.text
    assert mastery.json()["total_states"] == 1
    assert mastery.json()["counts"] == {"LEARNING": 1}
    assert mastery.json()["due_reviews"] == 1
    assert reviews.status_code == 200, reviews.text
    assert reviews.json()["page"]["total_items"] == 1
    assert reviews.json()["items"][0]["resource_id"] == str(resource.id)
    assert reviews.json()["items"][0]["gates"][0]["gate"] == "FACTUAL"


def test_agent_run_replay_view_is_scoped_ordered_and_redacted(
    client: TestClient, db_session: Session, read_context: ReadContext
) -> None:
    run = _seed_agent_run(db_session, read_context)
    foreign_run = AgentRun(
        external_run_id=f"run-{uuid4().hex}",
        event_id=f"event-{uuid4().hex}",
        trace_id=f"trace-{uuid4().hex}",
        tenant_id=read_context.foreign.tenant_id,
        student_id=read_context.foreign.id,
        status="QUEUED",
        latest_sequence=0,
        safe_input_snapshot={},
        safe_output_snapshot={},
    )
    db_session.add(foreign_run)
    db_session.flush()
    headers = _headers(read_context.admin_token)

    response = client.get(f"/api/v1/admin/agent-runs/{run.external_run_id}", headers=headers)
    foreign = client.get(f"/api/v1/admin/agent-runs/{foreign_run.external_run_id}", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["external_run_id"] == run.external_run_id
    assert body["tool_calls"][0]["sequence"] == 1
    assert body["input_snapshot"]["api_key"] == "***"
    assert "super-secret" not in response.text
    assert foreign.status_code == 404


def _seed_overview_counts(db: Session, context: ReadContext) -> None:
    """BE-017 seed: one of each countable entity per tenant.

    ``read_context`` already provides 2 ACTIVE students in the admin tenant
    (``first``, ``second``) and 1 ACTIVE student in a foreign tenant
    (``foreign``). This helper adds the remaining countable rows in both
    tenants so every overview metric can assert tenant-scoped isolation.
    """

    def _pending(tenant_id: UUID, label: str) -> User:
        # create_student_user defaults to PENDING and assigns STUDENT role.
        return create_student_user(
            db,
            tenant_id=tenant_id,
            email=f"{label}-{uuid4().hex}@example.com",
            password_hash=hash_password("PendingPass1!"),
            student_no=f"{label[0].upper()}-{uuid4().hex[:10]}",
            display_name=label,
        )

    def _reviewing_resource(tenant_id: UUID, student_id: UUID, tag: str) -> None:
        job = ResourceJobRecord(
            tenant_id=tenant_id,
            student_id=student_id,
            course_id=COURSE_ID,
            node_id=NODE_ID,
            idempotency_key=f"overview-{tag}-{uuid4().hex}",
            request_digest="b" * 64,
            status=ResourceJobStatus.REVIEWING,
            requested_types=[ResourceType.STRUCTURE_CARD.value],
            source_ids=["40000000-0000-8000-000000000001"],
            context_digest="c" * 64,
            progress_percent=0,
        )
        db.add(job)
        db.flush()
        db.add(
            LearningResourceRecord(
                tenant_id=tenant_id,
                job_id=job.id,
                resource_type=ResourceType.STRUCTURE_CARD,
                version=1,
                status=ResourceArtifactStatus.REVIEWING,
                source_ids=job.source_ids,
                context_digest=job.context_digest,
                content_digest=f"{tag[0]}" * 64,
                metadata_json={},
            )
        )

    def _due_review(tenant_id: UUID, student_id: UUID, tag: str) -> None:
        mastery = MasteryState(
            tenant_id=tenant_id,
            student_id=student_id,
            course_id=COURSE_ID,
            node_id=NODE_ID,
            status=MasteryStatus.LEARNING,
            version=1,
        )
        db.add(mastery)
        db.flush()
        db.add(
            ReviewSchedule(
                tenant_id=tenant_id,
                student_id=student_id,
                course_id=COURSE_ID,
                node_id=NODE_ID,
                mastery_state_id=mastery.id,
                scenario_key=f"overview-{tag}",
                due_at=NOW - timedelta(minutes=5),
                original_due_at=NOW - timedelta(minutes=5),
                hint_ceiling=0,
                status=ReviewStatus.DUE,
                version=1,
            )
        )

    # Admin tenant: 1 PENDING user, 1 REVIEWING resource, 1 DUE review.
    _pending(context.tenant.id, "AdminPending")
    _reviewing_resource(context.tenant.id, context.first.id, "admin")
    _due_review(context.tenant.id, context.first.id, "admin")

    # Foreign tenant: counterpart rows that must NOT inflate admin counts.
    _pending(context.foreign.tenant_id, "ForeignPending")
    _reviewing_resource(context.foreign.tenant_id, context.foreign.id, "foreign")
    _due_review(context.foreign.tenant_id, context.foreign.id, "foreign")
    db.flush()


class TestAdminOverview:
    """BE-017: live tenant-scoped aggregate counts replace hardcoded V1.0 stats."""

    def test_overview_returns_live_tenant_scoped_counts(
        self, client: TestClient, db_session: Session, read_context: ReadContext
    ) -> None:
        _seed_overview_counts(db_session, read_context)
        headers = _headers(read_context.admin_token)

        response = client.get("/api/v1/admin/overview", headers=headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body.keys()) == {
            "active_students",
            "pending_registrations",
            "resource_reviews",
            "due_reviews",
        }
        # 2 ACTIVE students in admin tenant (first + second); admin has
        # COURSE_ADMIN role so is excluded; foreign student must NOT leak.
        assert body["active_students"] == 2
        assert body["pending_registrations"] == 1
        assert body["resource_reviews"] == 1
        assert body["due_reviews"] == 1

    def test_overview_rejects_student_token(
        self, client: TestClient, db_session: Session, read_context: ReadContext
    ) -> None:
        _seed_overview_counts(db_session, read_context)
        token = _login(client, read_context.first.email, "StudentPass1!")

        response = client.get("/api/v1/admin/overview", headers=_headers(token))

        assert response.status_code == 403


# Distinct from NODE_ID so node-scoped mastery distribution can be asserted
# without colliding with the rows seeded by other helpers. Resolved at seed
# time to a real knowledge node (other than NODE_ID) so the mastery FK holds.
def _second_node_id(db: Session) -> UUID:
    row = db.execute(
        select(KnowledgeNode.id)
        .where(KnowledgeNode.course_id == COURSE_ID, KnowledgeNode.id != NODE_ID)
        .limit(1)
    ).scalar_one_or_none()
    assert row is not None, "seeded course must expose a second knowledge node"
    return row


def _seed_metrics_series(db: Session, context: ReadContext) -> UUID:
    """BE-028 seed: provider calls, agent runs, mastery, and resources.

    Places every event inside a single hour window starting at ``NOW`` so the
    hourly bucket (window <= 36h) deterministically contains all seeded rows.
    The foreign tenant gets mirror rows that must never leak into admin counts.
    Returns the second node id used for the STABLE_MASTERY row so the caller can
    assert the node-scoped distribution.
    """
    metrics_node_id = _second_node_id(db)

    def _provider_call(
        tenant_id: UUID,
        *,
        outcome: str,
        latency_ms: int,
        rate_limited: bool,
        offset_seconds: int,
    ) -> None:
        record_provider_call(
            db,
            tenant_id=tenant_id,
            provider_type=ProviderType.LLM,
            vendor="xfyun",
            model="spark-v4",
            operation="CHAT",
            outcome=outcome,
            latency_ms=latency_ms,
            rate_limited=rate_limited,
            trace_id=f"trace-{tenant_id.hex}-{offset_seconds}",
            created_at=NOW + timedelta(seconds=offset_seconds),
        )

    # Admin tenant: 3 succeeded + 1 failed + 1 throttled across the hour.
    admin_calls = [
        ("SUCCEEDED", 10, False, 10),
        ("SUCCEEDED", 20, False, 20),
        ("SUCCEEDED", 100, False, 30),
        ("FAILED", 40, False, 40),
        ("SUCCEEDED", 50, True, 50),
    ]
    for outcome, latency, rate_limited, offset in admin_calls:
        _provider_call(
            context.tenant.id,
            outcome=outcome,
            latency_ms=latency,
            rate_limited=rate_limited,
            offset_seconds=offset,
        )
    # Foreign tenant must not leak.
    _provider_call(
        context.foreign.tenant_id,
        outcome="SUCCEEDED",
        latency_ms=999,
        rate_limited=False,
        offset_seconds=15,
    )

    # Agent runs: 1 SUCCEEDED + 1 FAILED + 1 fallback inside the window.
    db.add(
        AgentRun(
            external_run_id=f"run-ok-{uuid4().hex}",
            event_id=f"event-ok-{uuid4().hex}",
            trace_id=f"trace-ok-{uuid4().hex}",
            tenant_id=context.tenant.id,
            student_id=context.first.id,
            status="SUCCEEDED",
            route="resource",
            latest_sequence=1,
            fallback_used=False,
            safe_input_snapshot={},
            safe_output_snapshot={},
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=2),
            created_at=NOW,
        )
    )
    db.add(
        AgentRun(
            external_run_id=f"run-fail-{uuid4().hex}",
            event_id=f"event-fail-{uuid4().hex}",
            trace_id=f"trace-fail-{uuid4().hex}",
            tenant_id=context.tenant.id,
            student_id=context.first.id,
            status="FAILED",
            route="coach",
            latest_sequence=1,
            fallback_used=False,
            error_code="PROVIDER_UNAVAILABLE",
            safe_input_snapshot={},
            safe_output_snapshot={},
            created_at=NOW + timedelta(minutes=1),
        )
    )
    db.add(
        AgentRun(
            external_run_id=f"run-fb-{uuid4().hex}",
            event_id=f"event-fb-{uuid4().hex}",
            trace_id=f"trace-fb-{uuid4().hex}",
            tenant_id=context.tenant.id,
            student_id=context.first.id,
            status="SUCCEEDED",
            route="fallback",
            latest_sequence=1,
            fallback_used=True,
            safe_input_snapshot={},
            safe_output_snapshot={},
            created_at=NOW + timedelta(minutes=2),
        )
    )
    db.add(
        AgentRun(
            external_run_id=f"run-foreign-{uuid4().hex}",
            event_id=f"event-foreign-{uuid4().hex}",
            trace_id=f"trace-foreign-{uuid4().hex}",
            tenant_id=context.foreign.tenant_id,
            student_id=context.foreign.id,
            status="SUCCEEDED",
            latest_sequence=1,
            fallback_used=False,
            safe_input_snapshot={},
            safe_output_snapshot={},
        )
    )

    # Mastery: 1 LEARNING at NODE_ID, 1 STABLE_MASTERY at metrics_node_id,
    # plus a foreign STABLE_MASTERY that must not leak.
    db.add(
        MasteryState(
            tenant_id=context.tenant.id,
            student_id=context.first.id,
            course_id=COURSE_ID,
            node_id=NODE_ID,
            status=MasteryStatus.LEARNING,
            version=1,
        )
    )
    db.add(
        MasteryState(
            tenant_id=context.tenant.id,
            student_id=context.first.id,
            course_id=COURSE_ID,
            node_id=metrics_node_id,
            status=MasteryStatus.STABLE_MASTERY,
            version=1,
        )
    )
    db.add(
        MasteryState(
            tenant_id=context.foreign.tenant_id,
            student_id=context.foreign.id,
            course_id=COURSE_ID,
            node_id=NODE_ID,
            status=MasteryStatus.STABLE_MASTERY,
            version=1,
        )
    )

    # Resource stats: 1 PUBLISHED + 1 REVIEWING STRUCTURE_CARD, plus a foreign row.
    published_job = ResourceJobRecord(
        tenant_id=context.tenant.id,
        student_id=context.first.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        idempotency_key=f"metrics-pub-{uuid4().hex}",
        request_digest="b" * 64,
        status=ResourceJobStatus.READY,
        requested_types=[ResourceType.STRUCTURE_CARD.value],
        source_ids=["40000000-0000-4000-8000-000000000001"],
        context_digest="c" * 64,
        progress_percent=100,
    )
    db.add(published_job)
    db.flush()
    published_resource = LearningResourceRecord(
        tenant_id=context.tenant.id,
        job_id=published_job.id,
        resource_type=ResourceType.STRUCTURE_CARD,
        version=1,
        status=ResourceArtifactStatus.PUBLISHED,
        source_ids=published_job.source_ids,
        context_digest=published_job.context_digest,
        content_digest="d" * 64,
        metadata_json={},
        published_at=NOW,
    )
    published_resource.created_at = NOW - timedelta(minutes=5)
    published_resource.updated_at = NOW
    db.add(published_resource)
    reviewing_job = ResourceJobRecord(
        tenant_id=context.tenant.id,
        student_id=context.first.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        idempotency_key=f"metrics-rev-{uuid4().hex}",
        request_digest="e" * 64,
        status=ResourceJobStatus.REVIEWING,
        requested_types=[ResourceType.STRUCTURE_CARD.value],
        source_ids=["40000000-0000-4000-8000-000000000002"],
        context_digest="f" * 64,
        progress_percent=0,
    )
    db.add(reviewing_job)
    db.flush()
    db.add(
        LearningResourceRecord(
            tenant_id=context.tenant.id,
            job_id=reviewing_job.id,
            resource_type=ResourceType.STRUCTURE_CARD,
            version=1,
            status=ResourceArtifactStatus.REVIEWING,
            source_ids=reviewing_job.source_ids,
            context_digest=reviewing_job.context_digest,
            content_digest="1" * 64,
            metadata_json={},
        )
    )
    foreign_job = ResourceJobRecord(
        tenant_id=context.foreign.tenant_id,
        student_id=context.foreign.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        idempotency_key=f"metrics-foreign-{uuid4().hex}",
        request_digest="9" * 64,
        status=ResourceJobStatus.READY,
        requested_types=[ResourceType.STRUCTURE_CARD.value],
        source_ids=["40000000-0000-4000-8000-000000000003"],
        context_digest="8" * 64,
        progress_percent=100,
    )
    db.add(foreign_job)
    db.flush()
    db.add(
        LearningResourceRecord(
            tenant_id=context.foreign.tenant_id,
            job_id=foreign_job.id,
            resource_type=ResourceType.STRUCTURE_CARD,
            version=1,
            status=ResourceArtifactStatus.PUBLISHED,
            source_ids=foreign_job.source_ids,
            context_digest=foreign_job.context_digest,
            content_digest="7" * 64,
            metadata_json={},
        )
    )
    db.flush()
    return metrics_node_id


class TestAdminMetrics:
    """BE-028: aggregate advanced metrics powering FE-025 charts and FE-026 stats."""

    def test_metrics_returns_hourly_buckets_with_usage_latency_and_rates(
        self, client: TestClient, db_session: Session, read_context: ReadContext
    ) -> None:
        _seed_metrics_series(db_session, read_context)
        headers = _headers(read_context.admin_token)

        response = client.get(
            "/api/v1/admin/metrics?since=2026-07-18T05:30:00Z&until=2026-07-18T07:30:00Z",
            headers=headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["window"]["bucket"] == "hour"
        assert body["window"]["bucket_count"] == 2
        # API usage: all 5 admin-tenant calls land in the 06:00 bucket.
        api_buckets = body["api_usage"]["buckets"]
        assert len(api_buckets) == 2
        busy = next(b for b in api_buckets if b["calls"] > 0)
        assert busy["calls"] == 5
        # Sorted latencies [10, 20, 40, 50, 100] -> p50 index 2 (=40), p95 index 4 (=100).
        assert busy["p50_latency_ms"] == 40
        assert busy["p95_latency_ms"] == 100
        assert busy["error_rate"] == pytest.approx(1 / 5)
        assert busy["throttle_rate"] == pytest.approx(1 / 5)

    def test_metrics_mastery_distribution_is_tenant_scoped_and_filters_node(
        self, client: TestClient, db_session: Session, read_context: ReadContext
    ) -> None:
        metrics_node_id = _seed_metrics_series(db_session, read_context)
        headers = _headers(read_context.admin_token)

        full = client.get(f"/api/v1/admin/metrics?course_id={COURSE_ID}", headers=headers)
        node_filtered = client.get(
            f"/api/v1/admin/metrics?course_id={COURSE_ID}&node_id={metrics_node_id}",
            headers=headers,
        )

        assert full.status_code == 200, full.text
        distribution = full.json()["mastery_distribution"]
        assert distribution["course_id"] == str(COURSE_ID)
        # Both admin-tenant rows counted; foreign STABLE_MASTERY excluded.
        assert distribution["total_states"] == 2
        assert distribution["counts"]["LEARNING"] == 1
        assert distribution["counts"]["STABLE_MASTERY"] == 1
        # Every MasteryStatus enum value is materialized.
        assert set(distribution["counts"].keys()) == {status.value for status in MasteryStatus}

        node_body = node_filtered.json()["mastery_distribution"]
        assert node_body["total_states"] == 1
        assert node_body["counts"] == {
            "STABLE_MASTERY": 1,
            **{
                status.value: 0
                for status in MasteryStatus
                if status != MasteryStatus.STABLE_MASTERY
            },
        }

    def test_metrics_agent_timeline_counts_outcomes_and_fallback(
        self, client: TestClient, db_session: Session, read_context: ReadContext
    ) -> None:
        _seed_metrics_series(db_session, read_context)
        headers = _headers(read_context.admin_token)

        response = client.get(
            "/api/v1/admin/metrics?since=2026-07-18T05:30:00Z&until=2026-07-18T07:30:00Z",
            headers=headers,
        )

        assert response.status_code == 200, response.text
        buckets = response.json()["agent_timeline"]["buckets"]
        busy = next(b for b in buckets if b["total"] > 0)
        # 3 admin-tenant runs in the window; foreign run excluded.
        assert busy["total"] == 3
        assert busy["succeeded"] == 2
        assert busy["failed"] == 1
        assert busy["fallback_used"] == 1

    def test_metrics_resource_stats_aggregate_per_type_and_success_rate(
        self, client: TestClient, db_session: Session, read_context: ReadContext
    ) -> None:
        _seed_metrics_series(db_session, read_context)
        headers = _headers(read_context.admin_token)

        response = client.get(f"/api/v1/admin/metrics?course_id={COURSE_ID}", headers=headers)

        assert response.status_code == 200, response.text
        items = response.json()["resource_stats"]["items"]
        assert len(items) == 1
        stat = items[0]
        assert stat["resource_type"] == "STRUCTURE_CARD"
        # 2 admin-tenant resources (1 PUBLISHED + 1 REVIEWING); foreign excluded.
        assert stat["total"] == 2
        assert stat["published"] == 1
        assert stat["reviewing"] == 1
        assert stat["success_rate"] == pytest.approx(0.5)
        # The published resource spans 5 min; the reviewing resource has
        # updated_at == created_at (0 ms), so the mean is 150_000 ms.
        assert stat["avg_generation_ms"] is not None
        assert stat["avg_generation_ms"] == pytest.approx(5 * 60 * 1000 / 2, rel=1e-6)

    def test_metrics_rejects_student_token_and_invalid_window(
        self, client: TestClient, db_session: Session, read_context: ReadContext
    ) -> None:
        _seed_metrics_series(db_session, read_context)
        headers = _headers(read_context.admin_token)

        student_token = _login(client, read_context.first.email, "StudentPass1!")
        denied = client.get("/api/v1/admin/metrics", headers=_headers(student_token))
        inverted = client.get(
            "/api/v1/admin/metrics?since=2026-07-18T07:30:00Z&until=2026-07-18T05:30:00Z",
            headers=headers,
        )

        assert denied.status_code == 403
        assert inverted.status_code == 422
