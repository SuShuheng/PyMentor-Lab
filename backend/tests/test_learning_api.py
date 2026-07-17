"""Student learning-loop API integration tests (BE-004)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.evidence import record_evidence
from app.idempotency import get_or_create_idempotency
from app.main import create_app
from app.mastery import AssessmentFacts, MasteryPolicy, record_assessment_and_decide
from app.models import (
    AuditEvent,
    LearningPath,
    MasteryState,
    MasteryStatus,
    OutboxEvent,
    ProfileVersion,
    ReviewStatus,
    TaskDefinition,
    TaskInstanceStatus,
    User,
    UserStatus,
)
from app.pathing import (
    PathProposal,
    StepProposal,
    ValidationContext,
    persist_validated_path,
    validate_path,
)
from app.profile_projection import DimensionUpdate, project_profile
from app.reviews import mark_due_reviews
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant
from app.task_compiler import CompileInput, compile_task_version, start_task_instance

COURSE_ID = UUID("00000000-0000-0000-0000-000000000401")
NODE_ID = UUID("00000000-0000-0000-0000-000000000402")
OTHER_NODE_ID = UUID("00000000-0000-0000-0000-000000000403")
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
        email=f"learning-{uuid4().hex}@example.com",
        password_hash=hash_password(password),
    )
    user.status = UserStatus.ACTIVE
    db_session.flush()
    response = client.post("/api/v1/auth/login", json={"email": user.email, "password": password})
    assert response.status_code == 200, response.text
    return user, response.json()["access_token"]


def _headers(token: str, key: str | None = None, trace_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    if trace_id is not None:
        headers["x-trace-id"] = trace_id
    return headers


def _project(db_session: Session, user: User, event_id: str) -> ProfileVersion:
    return project_profile(
        db_session,
        tenant_id=user.tenant_id,
        student_id=user.id,
        source_event_id=event_id,
        expected_version=0,
        updates=[
            DimensionUpdate(
                dimension="DEBUGGING",
                scope_key="loops",
                score=0.65,
                confidence=0.9,
                support_level=1,
            )
        ],
    )


def _task_version(db_session: Session, user: User):
    definition = TaskDefinition(
        tenant_id=user.tenant_id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        key=f"api-loop-{uuid4().hex}",
        title="API loop task",
    )
    db_session.add(definition)
    db_session.flush()
    return compile_task_version(
        db_session,
        definition,
        CompileInput(
            prompt="Fix the loop boundary",
            tests_policy={
                "entrypoint": {"kind": "FUNCTION", "name": "solve"},
                "allowed_imports": ["math"],
                "visible": [
                    {
                        "id": "visible-boundary",
                        "args": [[1, 2]],
                        "kwargs": {},
                        "expected": 3,
                        "comparison": "EQUAL",
                        "transfer": False,
                    }
                ],
                "hidden": [
                    {
                        "id": "hidden-upper-bound",
                        "args": [[0, 0]],
                        "kwargs": {},
                        "expected": 0,
                        "comparison": "EQUAL",
                        "transfer": True,
                    }
                ],
            },
            hint_policy={
                "max_level": 2,
                "hints": [
                    {
                        "key": "inspect-range",
                        "level": 1,
                        "content": "Inspect the range bounds.",
                        "independence_cost": 10,
                    },
                    {
                        "key": "compare-stop",
                        "level": 2,
                        "content": "Compare the stop value with the target.",
                        "independence_cost": 25,
                    },
                ],
            },
            mastery_policy={
                "independence_min": 0.7,
                "transfer_min": 0.6,
                "max_hints_for_mastery": 1,
                "review_delay_days": 7,
            },
            resource_versions={"lesson": "loops@1"},
            scenario_key="range-stop-v1",
        ),
    )


def _initial_mastery(db_session: Session, user: User, *, now: datetime = NOW):
    return record_assessment_and_decide(
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
        evidence_event_id=f"evt_api_initial_{uuid4().hex}",
        now=now,
    )


def _path(db_session: Session, user: User) -> LearningPath:
    validated = validate_path(
        PathProposal(steps=[StepProposal(node_id=OTHER_NODE_ID, estimated_minutes=20)]),
        ValidationContext(
            daily_minutes=30,
            prerequisites={},
            completed_nodes=set(),
            due_reviews=[],
            mastery_policy_nodes={OTHER_NODE_ID},
            resource_ready_nodes={OTHER_NODE_ID},
            active_node_ids=set(),
            template_fallback_nodes=set(),
            forbidden_node_ids=set(),
        ),
    )
    return persist_validated_path(
        db_session,
        tenant_id=user.tenant_id,
        student_id=user.id,
        course_id=COURSE_ID,
        expected_version=0,
        validated=validated,
    )


def test_current_profile_is_student_scoped(
    client: TestClient, db_session: Session, student_auth
) -> None:
    student, token = student_auth
    own = _project(db_session, student, "evt_own_profile")
    other_tenant = get_or_create_tenant(db_session, slug=f"other-{uuid4().hex}", name="Other")
    db_session.flush()
    other = create_student_user(
        db_session,
        tenant_id=other_tenant.id,
        email=f"other-{uuid4().hex}@example.com",
        password_hash=hash_password("ValidPass1!"),
    )
    db_session.flush()
    _project(db_session, other, "evt_other_profile")

    response = client.get("/api/v1/profiles/current", headers=_headers(token))
    assert response.status_code == 200, response.text
    assert response.json()["student_id"] == str(student.id)
    assert response.json()["version"] == own.version


def test_today_prioritizes_due_review(
    client: TestClient, db_session: Session, student_auth
) -> None:
    student, token = student_auth
    path = _path(db_session, student)
    decision = _initial_mastery(db_session, student, now=NOW - timedelta(days=7))
    assert decision.review is not None
    mark_due_reviews(db_session, now=NOW)

    response = client.get("/api/v1/learning/today", headers=_headers(token))
    assert response.status_code == 200, response.text
    assert response.json()[0]["kind"] == "REVIEW"
    assert any(
        item["id"] == str(path.id) or item["node_id"] == str(OTHER_NODE_ID)
        for item in response.json()
    )


def test_path_mastery_and_due_review_reads(
    client: TestClient, db_session: Session, student_auth
) -> None:
    student, token = student_auth
    path = _path(db_session, student)
    decision = _initial_mastery(db_session, student, now=NOW - timedelta(days=7))
    assert decision.state is not None and decision.review is not None
    mark_due_reviews(db_session, now=NOW)

    path_response = client.get("/api/v1/paths/current", headers=_headers(token))
    mastery_response = client.get("/api/v1/mastery", headers=_headers(token))
    review_response = client.get("/api/v1/reviews/due", headers=_headers(token))
    assert path_response.status_code == 200
    assert path_response.json()["id"] == str(path.id)
    assert mastery_response.status_code == 200
    assert mastery_response.json()[0]["status"] == "REVIEW_REQUIRED"
    assert review_response.status_code == 200
    assert review_response.json()[0]["status"] == "DUE"


def test_task_start_replay_returns_same_instance_and_commits_events(
    client: TestClient, db_session: Session, student_auth
) -> None:
    student, token = student_auth
    version = _task_version(db_session, student)
    headers = _headers(token, "start-task-001", "trc_start_task")
    first = client.post(f"/api/v1/tasks/{version.id}/start", headers=headers)
    second = client.post(f"/api/v1/tasks/{version.id}/start", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    public_snapshot = first.json()["snapshot"]
    assert "hidden" not in public_snapshot["tests_policy"]
    assert public_snapshot["hint_policy"] == {"max_level": 2}
    assert "hidden-upper-bound" not in first.text
    assert "Compare the stop value with the target." not in first.text
    assert (
        db_session.scalar(select(AuditEvent).where(AuditEvent.trace_id == "trc_start_task"))
        is not None
    )
    assert (
        db_session.scalar(select(OutboxEvent).where(OutboxEvent.trace_id == "trc_start_task"))
        is not None
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.trace_id == "trc_start_task")
        )
        == 1
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.trace_id == "trc_start_task")
        )
        == 1
    )


def test_write_requires_idempotency_key(
    client: TestClient, db_session: Session, student_auth
) -> None:
    student, token = student_auth
    version = _task_version(db_session, student)
    response = client.post(f"/api/v1/tasks/{version.id}/start", headers=_headers(token))
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_pending_idempotency_reservation_returns_conflict(
    client: TestClient, db_session: Session, student_auth
) -> None:
    student, token = student_auth
    version = _task_version(db_session, student)
    endpoint = f"POST /api/v1/tasks/{version.id}/start"
    get_or_create_idempotency(
        db_session,
        key="pending-task-start",
        tenant_id=student.tenant_id,
        user_id=student.id,
        endpoint=endpoint,
    )
    response = client.post(
        f"/api/v1/tasks/{version.id}/start",
        headers=_headers(token, "pending-task-start"),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


def test_cross_tenant_task_version_is_denied(
    client: TestClient, db_session: Session, student_auth
) -> None:
    _, token = student_auth
    other_tenant = get_or_create_tenant(db_session, slug=f"task-other-{uuid4().hex}", name="Other")
    db_session.flush()
    other = create_student_user(
        db_session,
        tenant_id=other_tenant.id,
        email=f"task-other-{uuid4().hex}@example.com",
        password_hash=hash_password("ValidPass1!"),
    )
    db_session.flush()
    version = _task_version(db_session, other)
    response = client.post(
        f"/api/v1/tasks/{version.id}/start",
        headers=_headers(token, "cross-tenant-start"),
    )
    assert response.status_code in {403, 404}


def test_profile_dispute_is_atomic_and_idempotent(
    client: TestClient, db_session: Session, student_auth
) -> None:
    student, token = student_auth
    profile = _project(db_session, student, "evt_dispute_profile")
    headers = _headers(token, "dispute-001", "trc_dispute")
    body = {
        "profile_version_id": str(profile.id),
        "reason": "The score omits my accepted debugging evidence.",
    }
    first = client.post("/api/v1/profiles/disputes", json=body, headers=headers)
    second = client.post("/api/v1/profiles/disputes", json=body, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert (
        db_session.scalar(select(AuditEvent).where(AuditEvent.trace_id == "trc_dispute"))
        is not None
    )
    assert (
        db_session.scalar(select(OutboxEvent).where(OutboxEvent.trace_id == "trc_dispute"))
        is not None
    )


def test_task_submission_consumes_scoped_evidence_and_decides_mastery(
    client: TestClient, db_session: Session, student_auth
) -> None:
    student, token = student_auth
    version = _task_version(db_session, student)
    instance = start_task_instance(
        db_session,
        student_id=student.id,
        task_version_id=version.id,
        active_key="submission-test",
    )
    event_id = f"evt_submit_{uuid4().hex}"
    record_evidence(
        db_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        event_id=event_id,
        event_type="ASSESSMENT_RECORDED",
        trace_id="trc_submit_evidence",
        course_id=COURSE_ID,
        node_id=NODE_ID,
        task_id=instance.id,
        payload={
            "correct": True,
            "hidden_tests_passed": True,
            "hints_used": 0,
            "support_level": 0,
            "independence_score": 0.9,
            "transfer_score": 0.8,
            "platform_error": False,
        },
    )
    response = client.post(
        f"/api/v1/tasks/{instance.id}/submit",
        json={"evidence_event_id": event_id, "expected_task_version": 1},
        headers=_headers(token, "submit-001", "trc_submit"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "INITIAL_MASTERY"
    assert instance.status == TaskInstanceStatus.COMPLETED
    state = db_session.scalar(select(MasteryState).where(MasteryState.student_id == student.id))
    assert state is not None and state.status == MasteryStatus.INITIAL_MASTERY
    assert (
        db_session.scalar(select(AuditEvent).where(AuditEvent.trace_id == "trc_submit")) is not None
    )
    assert (
        db_session.scalar(select(OutboxEvent).where(OutboxEvent.trace_id == "trc_submit"))
        is not None
    )


def test_review_reschedule_is_atomic_and_versioned(
    client: TestClient, db_session: Session, student_auth
) -> None:
    student, token = student_auth
    decision = _initial_mastery(db_session, student, now=datetime.now(UTC))
    assert decision.review is not None
    review = decision.review
    due_at = review.due_at + timedelta(days=2)
    response = client.post(
        f"/api/v1/reviews/{review.id}/reschedule",
        json={"due_at": due_at.isoformat(), "expected_version": review.version},
        headers=_headers(token, "review-reschedule-001", "trc_reschedule"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["due_at"] == due_at.isoformat()
    assert review.status == ReviewStatus.SCHEDULED
    assert review.reschedule_count == 1
    assert (
        db_session.scalar(select(AuditEvent).where(AuditEvent.trace_id == "trc_reschedule"))
        is not None
    )
    assert (
        db_session.scalar(select(OutboxEvent).where(OutboxEvent.trace_id == "trc_reschedule"))
        is not None
    )
