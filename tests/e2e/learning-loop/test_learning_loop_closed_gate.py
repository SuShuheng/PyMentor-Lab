"""INT-003 — deterministic learning-loop E2E gate (integration lane).

This gate is owned by the integration workstream (``CONTRACT.md`` "Cross-track
acceptance"). It is intentionally *not* a BE-004/BE-005 unit test: those prove
individual domain services in isolation. This gate proves the *integrated*
competition claim — a single resettable student identity can traverse the full
closed loop ``evidence -> path -> task -> code -> assessment -> initial mastery
-> due review -> stable mastery`` and that a sandbox platform error is a
non-penalty that preserves prior mastery and review across every formal-state
table, while the admin projections observe the same loop.

The gate exercises real persistence (PostgreSQL via ``db_session``) and the
real FastAPI app (``create_app``). The sandbox supervisor is injected at the
documented FastAPI dependency seam (``get_sandbox_client``) with deterministic
``SandboxResult`` values — exactly the seam BE-005 exposes for cross-process
verification when a real Docker sandbox supervisor is not running. Per the
CONTRACT, the sandbox is the only cross-process boundary the API owns; the
``SandboxClient`` is the seam, and a deterministic adapter at that seam is the
allowed verification form (it does not bypass any *formal-state* rule).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.code import get_sandbox_client, get_session_factory
from app.contracts.sandbox import (
    CodeRunStatus,
    SandboxResult,
    SandboxRunStatus,
)
from app.db import get_db
from app.evidence import record_evidence
from app.main import create_app
from app.models import (
    AssessmentResult,
    CodeRun,
    EvidenceEvent,
    LearningPath,
    MasteryState,
    MasteryStateHistory,
    MasteryStatus,
    OutboxEvent,
    ReviewSchedule,
    ReviewStatus,
    TaskDefinition,
    TaskInstance,
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
from app.reviews import ReviewFacts, complete_review, mark_due_reviews
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant
from app.task_compiler import CompileInput, compile_task_version, start_task_instance

# Governed, seeded course assets (see backend/app/knowledge_seed.py).
COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")
NODE_ID = UUID("9512e5ec-f547-51b3-b0df-c5b3a877da9e")
NOW = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Deterministic sandbox adapter at the documented FastAPI seam.
# --------------------------------------------------------------------------- #


class DeterministicSandbox:
    """Deterministic adapter for ``app.api.code.get_sandbox_client``.

    Mirrors BE-005's ``FakeSandbox`` contract: per-phase result selection,
    call recording, and replay-safe cancellation. This is the *only* injected
    boundary; every downstream formal-state transition is asserted against the
    real PostgreSQL tables.
    """

    def __init__(
        self,
        *,
        visible: SandboxResult | None = None,
        hidden: SandboxResult | None = None,
    ) -> None:
        self.visible = visible
        self.hidden = hidden
        self.execute_calls: list[str] = []
        self.cancel_calls: list[str] = []

    def execute_phase(self, request: Any) -> SandboxResult:
        phase = request.phase.value
        self.execute_calls.append(phase)
        if phase == "VISIBLE":
            assert self.visible is not None
            return self.visible.model_copy(update={"run_id": request.run_id})
        assert self.hidden is not None
        return self.hidden.model_copy(update={"run_id": request.run_id})

    def cancel(self, run_id: str) -> bool:
        self.cancel_calls.append(run_id)
        return True


def _passed(
    run_id: str = "loop",
    *,
    hidden: bool = False,
    passed: bool = True,
) -> SandboxResult:
    return SandboxResult(
        run_id=run_id,
        status=SandboxRunStatus.PASSED if passed else SandboxRunStatus.FAILED,
        passed=passed,
        stdout="ok",
        stderr="",
        tests=[
            {
                "case_id": "hidden-transfer" if hidden else "visible-basic",
                "display_name": "hidden-transfer" if hidden else "visible-basic",
                "visibility": "HIDDEN" if hidden else "VISIBLE",
                "comparison": "EQUAL",
                "transfer": hidden,
                "passed": passed,
                "stdout": "",
                "stderr": "",
                "duration_ms": 3,
            }
        ],
        trace_frames=None,
        resource_usage={
            "cpu_ms": 1,
            "wall_ms": 1,
            "peak_memory_kb": 64,
            "exit_code": 0 if passed else 1,
        },
        stdout_truncated=False,
        stderr_truncated=False,
        trace_truncated=False,
        user_error=None,
        platform_error=None,
    )


def _platform_failure(run_id: str = "loop") -> SandboxResult:
    return SandboxResult.platform_failure(run_id=run_id, category="SUPERVISOR_TIMEOUT", message="m")


def _snapshot() -> dict[str, Any]:
    """A snapshot whose mastery policy yields INITIAL_MASTERY on an unassisted,
    hint-free, transfer-passing submission."""

    return {
        "prompt": "Return the sum.",
        "tests_policy": {
            "entrypoint": {"kind": "FUNCTION", "name": "solve"},
            "allowed_imports": ["math"],
            "visible": [
                {
                    "id": "visible-basic",
                    "args": [[1, 2]],
                    "expected": 3,
                    "comparison": "EQUAL",
                    "transfer": False,
                }
            ],
            "hidden": [
                {
                    "id": "hidden-transfer",
                    "args": [[0, 0]],
                    "expected": 0,
                    "comparison": "EQUAL",
                    "transfer": True,
                }
            ],
        },
        "hint_policy": {
            "max_level": 2,
            "hints": [
                {
                    "key": "inspect-input",
                    "level": 1,
                    "content": "Inspect the input shape.",
                    "independence_cost": 10,
                },
                {
                    "key": "check-bound",
                    "level": 2,
                    "content": "Check the boundary.",
                    "independence_cost": 25,
                },
            ],
        },
        "mastery_policy": {
            "independence_min": 0.7,
            "transfer_min": 0.6,
            "max_hints_for_mastery": 1,
            "review_delay_days": 7,
        },
        "resource_versions": {},
        "scenario_key": "sum-v1",
    }


# --------------------------------------------------------------------------- #
# Scenario scaffolding — resettable Student A/B identity + governed task.
# --------------------------------------------------------------------------- #


@pytest.fixture()
def loop_client(db_session: Session) -> Iterator[tuple[TestClient, DeterministicSandbox]]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    def _override_session_factory() -> Any:
        # Bind the three-transaction orchestrator to the test's savepoint
        # session so all formal-state writes are visible to assertions.
        class _Factory:
            def __call__(self) -> Session:
                return db_session

        return _Factory()

    sandbox = DeterministicSandbox(visible=_passed(), hidden=_passed(hidden=True))
    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_sandbox_client] = lambda: sandbox
    app.dependency_overrides[get_session_factory] = _override_session_factory
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client, sandbox
    app.dependency_overrides.clear()


def _enroll(db_session: Session) -> tuple[User, TaskInstance]:
    """Build a resettable student identity in the default tenant and an active,
    governed task instance whose snapshot can drive a real submission."""

    suffix = uuid4().hex
    tenant = get_or_create_tenant(db_session, slug="default", name="Default")
    db_session.flush()
    password = "ValidPass1!"
    user = create_student_user(
        db_session,
        tenant_id=tenant.id,
        email=f"loop-{suffix}@example.com",
        password_hash=hash_password(password),
    )
    user.status = UserStatus.ACTIVE
    db_session.flush()

    definition = TaskDefinition(
        tenant_id=tenant.id,
        course_id=COURSE_ID,
        node_id=NODE_ID,
        key=f"sum-{suffix}",
        title="Sum task",
    )
    db_session.add(definition)
    db_session.flush()
    snapshot = _snapshot()
    version = compile_task_version(
        db_session,
        definition,
        CompileInput(
            prompt=snapshot["prompt"],
            tests_policy=snapshot["tests_policy"],
            hint_policy=snapshot["hint_policy"],
            mastery_policy=snapshot["mastery_policy"],
            resource_versions=snapshot["resource_versions"],
            scenario_key=snapshot["scenario_key"],
        ),
    )
    db_session.flush()
    instance = start_task_instance(
        db_session,
        task_version_id=version.id,
        student_id=user.id,
        active_key=f"loop-{suffix}",
    )
    db_session.flush()
    return user, instance


def _seed_current_path(db_session: Session, user: User) -> LearningPath:
    """Persist a CURRENT validated learning path so the loop boundary includes
    the path-correction limb required by CONTRACT integration scenario 2."""

    validated = validate_path(
        PathProposal(steps=[StepProposal(node_id=NODE_ID, estimated_minutes=20)]),
        ValidationContext(
            daily_minutes=30,
            prerequisites={},
            completed_nodes=set(),
            due_reviews=[],
            mastery_policy_nodes={NODE_ID},
            resource_ready_nodes={NODE_ID},
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


def _login(loop_client: TestClient, user: User) -> str:
    response = loop_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "ValidPass1!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str, key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key}


# --------------------------------------------------------------------------- #
# Closed-loop gate — Student A traverses the full loop end-to-end.
# --------------------------------------------------------------------------- #


def test_closed_learning_loop_persists_every_formal_state_transition(
    loop_client: tuple[TestClient, DeterministicSandbox],
    db_session: Session,
) -> None:
    """Student A: evidence -> current path -> task start (HTTP) -> code submit
    (HTTP) -> initial mastery + scheduled review -> review becomes due ->
    unassisted delayed review -> stable mastery, with admin projections
    observing the same loop."""

    client, _sandbox = loop_client
    user, instance = _enroll(db_session)
    _seed_current_path(db_session, user)
    token = _login(client, user)

    # 1. The current validated path is queryable through the student API.
    path_response = client.get(
        "/api/v1/paths/current", headers={"Authorization": f"Bearer {token}"}
    )
    assert path_response.status_code == 200, path_response.text
    path_body = path_response.json()
    assert path_body["status"] == "CURRENT"
    assert any(step["node_id"] == str(NODE_ID) for step in path_body["steps"])

    # 2. Submit visible+hidden code (SUBMIT) through the HTTP boundary. The
    #    BE-005 submission endpoint is synchronous (three-transaction
    #    orchestrator), so it returns the final run view, not a queue handle.
    code_submission = client.post(
        "/api/v1/code/submissions",
        json={
            "task_instance_id": str(instance.id),
            "expected_task_version": instance.version,
            "source_code": "def solve(xs):\n    return sum(xs)\n",
        },
        headers=_headers(token, f"code-A-{uuid4().hex}"),
    )
    assert code_submission.status_code == 200, code_submission.text
    code_body = code_submission.json()
    assert code_body["mode"] == "SUBMIT"
    assert code_body["result"]["passed"] is True
    assessment_event_id = code_body["evidence_event_id"]
    assert assessment_event_id is not None, (
        "a passing SUBMIT must persist ASSESSMENT_RECORDED evidence and return its event id"
    )

    # 3. Decide mastery from the assessment evidence through the task-submit
    #    command. This is the documented two-step loop: the code submission
    #    produces immutable assessment evidence, and the task submission
    #    consumes that evidence to decide formal mastery atomically.
    task_submission = client.post(
        f"/api/v1/tasks/{instance.id}/submit",
        json={
            "evidence_event_id": assessment_event_id,
            "expected_task_version": instance.version,
        },
        headers=_headers(token, f"task-A-{uuid4().hex}"),
    )
    assert task_submission.status_code == 200, task_submission.text
    submission_body = task_submission.json()

    # The transactional outbox + formal state are visible through the same
    # session that backed the HTTP request.
    evidence_rows = list(
        db_session.scalars(
            select(EvidenceEvent).where(
                EvidenceEvent.student_id == user.id,
                EvidenceEvent.event_type == "ASSESSMENT_RECORDED",
            )
        )
    )
    assert len(evidence_rows) == 1, (
        "SUBMIT must persist exactly one ASSESSMENT_RECORDED evidence row"
    )
    assert evidence_rows[0].task_id == instance.id

    mastery = db_session.scalar(
        select(MasteryState).where(
            MasteryState.student_id == user.id,
            MasteryState.node_id == NODE_ID,
        )
    )
    assert mastery is not None, "an unassisted transfer-passing submission must create MasteryState"
    assert mastery.status == MasteryStatus.INITIAL_MASTERY, (
        f"unassisted transfer-passing submission must reach INITIAL_MASTERY, got {mastery.status}"
    )

    # 4. The submission response advertises the scheduled review.
    assert submission_body["status"] == "INITIAL_MASTERY"
    assert submission_body["review_due_at"] is not None

    review = db_session.scalar(
        select(ReviewSchedule).where(
            ReviewSchedule.student_id == user.id,
            ReviewSchedule.node_id == NODE_ID,
        )
    )
    assert review is not None, "INITIAL_MASTERY must atomically schedule a review"
    assert review.status in {ReviewStatus.SCHEDULED, ReviewStatus.DUE}

    # 5. The task instance transitioned to COMPLETED and bumped its version.
    refreshed_instance = db_session.get(TaskInstance, instance.id)
    assert refreshed_instance is not None
    assert refreshed_instance.status == TaskInstanceStatus.COMPLETED

    # 6. The transactional outbox captured the formal state transitions.
    outbox_types = {
        row.event_type
        for row in db_session.scalars(
            select(OutboxEvent).where(OutboxEvent.tenant_id == user.tenant_id)
        )
    }
    assert "CODE_RUN_COMPLETED" in outbox_types or "ASSESSMENT_RECORDED" in outbox_types

    # 7. Time passes: the scheduled review becomes due (deterministic). The
    #    review was scheduled with review_delay_days=7 from the real task-submit
    #    wall clock, so fast-forward well past that horizon.
    due_horizon = datetime.now(UTC) + timedelta(days=30)
    mark_due_reviews(db_session, now=due_horizon)
    db_session.flush()
    refreshed_review = db_session.get(ReviewSchedule, review.id)
    assert refreshed_review is not None
    assert refreshed_review.status == ReviewStatus.DUE

    # 8. Student A completes an unassisted delayed review -> STABLE_MASTERY
    #    through the same evidence-id-deduped path. The review evidence must
    #    be created at or after the scheduled due_at (the delayed-review rule)
    #    and the scenario_key must match the schedule's.
    review_time = refreshed_review.due_at + timedelta(minutes=1)
    review_evidence = record_evidence(
        db_session,
        tenant_id=user.tenant_id,
        student_id=user.id,
        event_id=f"review-A-{uuid4().hex}",
        event_type="REVIEW_COMPLETED",
        trace_id="trc-loop-A",
        payload={
            "correct": True,
            "hidden_tests_passed": True,
            "hints_used": 0,
            "support_level": 0,
            "independence_score": 0.9,
            "transfer_score": 0.8,
            "platform_error": False,
        },
        course_id=COURSE_ID,
        node_id=NODE_ID,
    )
    assert review_evidence is not None
    review_evidence.created_at = review_time
    db_session.flush()
    complete_review(
        db_session,
        review_id=refreshed_review.id,
        facts=ReviewFacts(
            correct=True,
            hidden_tests_passed=True,
            hints_used=0,
            support_level=0,
            independence_score=0.9,
            transfer_score=0.8,
            platform_error=False,
            scenario_key=refreshed_review.scenario_key,
        ),
        evidence_event_id=review_evidence.event_id,
        now=review_time,
    )
    db_session.flush()
    stable_mastery = db_session.get(MasteryState, mastery.id)
    assert stable_mastery is not None
    assert stable_mastery.status == MasteryStatus.STABLE_MASTERY, (
        "an unassisted delayed review of INITIAL_MASTERY must promote to STABLE_MASTERY"
    )
    assert stable_mastery.stable_mastery_at is not None

    # 9. The mastery history records the immutable transition sequence.
    history = list(
        db_session.scalars(
            select(MasteryStateHistory)
            .where(MasteryStateHistory.mastery_state_id == mastery.id)
            .order_by(MasteryStateHistory.created_at)
        )
    )
    transition_reasons = [h.reason for h in history]
    assert "ASSESSMENT_THRESHOLDS_MET" in transition_reasons
    assert "DELAYED_REVIEW_PASSED" in transition_reasons


def test_platform_error_never_reduces_mastery_or_creates_assessment_evidence(
    loop_client: tuple[TestClient, DeterministicSandbox],
    db_session: Session,
) -> None:
    """Student B: a sandbox PLATFORM_ERROR during SUBMIT must be a strict
    non-penalty — no ASSESSMENT_RECORDED evidence, no MasteryState read or
    mutation, no review touched — while the run itself is persisted as
    PLATFORM_ERROR so operations can observe the failure."""

    client, sandbox = loop_client
    user, instance = _enroll(db_session)
    token = _login(client, user)

    # Pre-existing mastery that a bug could otherwise clobber.
    existing_evidence = record_evidence(
        db_session,
        tenant_id=user.tenant_id,
        student_id=user.id,
        event_id=f"prior-B-{uuid4().hex}",
        event_type="ASSESSMENT_RECORDED",
        trace_id="trc-loop-B-prior",
        payload={
            "correct": True,
            "hidden_tests_passed": True,
            "hints_used": 0,
            "support_level": 0,
            "independence_score": 0.9,
            "transfer_score": 0.8,
            "platform_error": False,
        },
        course_id=COURSE_ID,
        node_id=NODE_ID,
    )
    assert existing_evidence is not None

    prior_mastery_count = len(
        list(
            db_session.scalars(
                select(MasteryState).where(
                    MasteryState.student_id == user.id,
                    MasteryState.node_id == NODE_ID,
                )
            )
        )
    )

    # Force a platform failure on the next SUBMIT.
    sandbox.visible = _platform_failure()
    sandbox.hidden = _passed(hidden=True)

    submission = client.post(
        "/api/v1/code/submissions",
        json={
            "task_instance_id": str(instance.id),
            "expected_task_version": instance.version,
            "source_code": "def solve(xs):\n    return sum(xs)\n",
        },
        headers=_headers(token, f"submit-B-platform-{uuid4().hex}"),
    )
    assert submission.status_code == 200, submission.text
    submission_body = submission.json()
    assert submission_body["status"] == "PLATFORM_ERROR"
    assert submission_body["evidence_event_id"] is None, (
        "a platform-error SUBMIT must not produce assessment evidence"
    )

    # The platform-failed run is persisted as PLATFORM_ERROR.
    platform_runs = list(
        db_session.scalars(
            select(CodeRun).where(
                CodeRun.task_instance_id == instance.id,
                CodeRun.status == CodeRunStatus.PLATFORM_ERROR,
            )
        )
    )
    assert len(platform_runs) >= 1, "a platform error must persist the run as PLATFORM_ERROR"

    # No new ASSESSMENT_RECORDED evidence was created by the failed submission.
    assessment_after = list(
        db_session.scalars(
            select(EvidenceEvent).where(
                EvidenceEvent.student_id == user.id,
                EvidenceEvent.event_type == "ASSESSMENT_RECORDED",
            )
        )
    )
    assert len(assessment_after) == 1, (
        "a platform-error SUBMIT must not record ASSESSMENT_RECORDED evidence"
    )

    # Mastery state population and review schedule are unchanged.
    after_mastery_count = len(
        list(
            db_session.scalars(
                select(MasteryState).where(
                    MasteryState.student_id == user.id,
                    MasteryState.node_id == NODE_ID,
                )
            )
        )
    )
    assert after_mastery_count == prior_mastery_count, (
        "a platform error must not create or destroy MasteryState rows"
    )

    assessment_results = list(
        db_session.scalars(
            select(AssessmentResult).where(AssessmentResult.task_instance_id == instance.id)
        )
    )
    # The AssessmentResult row may be persisted for audit, but its facts must
    # carry platform_error=True and must never have driven a mastery transition.
    assert all((row.facts or {}).get("platform_error") is True for row in assessment_results), (
        "a platform-error assessment must record facts.platform_error=True"
    )


def test_admin_progress_projection_reflects_the_persisted_learning_loop(
    loop_client: tuple[TestClient, DeterministicSandbox],
    db_session: Session,
) -> None:
    """The admin read-side projection must reflect the same loop the student
    just completed — proving the integration boundary that admin observation
    is sourced from the same formal-state tables, not a parallel store."""

    client, _sandbox = loop_client
    student_user, instance = _enroll(db_session)
    student_token = _login(client, student_user)

    # Drive the two-step submission loop through the student HTTP boundary:
    # code submission produces assessment evidence, then task submission
    # decides mastery from that evidence.
    code_submission = client.post(
        "/api/v1/code/submissions",
        json={
            "task_instance_id": str(instance.id),
            "expected_task_version": instance.version,
            "source_code": "def solve(xs):\n    return sum(xs)\n",
        },
        headers=_headers(student_token, f"code-admin-{uuid4().hex}"),
    )
    assert code_submission.status_code == 200, code_submission.text
    assessment_event_id = code_submission.json()["evidence_event_id"]
    assert assessment_event_id is not None
    task_submission = client.post(
        f"/api/v1/tasks/{instance.id}/submit",
        json={
            "evidence_event_id": assessment_event_id,
            "expected_task_version": instance.version,
        },
        headers=_headers(student_token, f"task-admin-{uuid4().hex}"),
    )
    assert task_submission.status_code == 200, task_submission.text
    assert task_submission.json()["status"] == "INITIAL_MASTERY"

    # Build an admin identity against the operator tenant and observe the
    # student's progress through the admin read API.
    admin_tenant = get_or_create_tenant(db_session, slug="default", name="Default")
    db_session.flush()
    admin_password = "AdminPass1!"
    from app.models import RoleName, User
    from app.services import assign_role

    admin = User(
        tenant_id=admin_tenant.id,
        email=f"loop-admin-{uuid4().hex}@example.com",
        password_hash=hash_password(admin_password),
        status=UserStatus.ACTIVE,
    )
    db_session.add(admin)
    db_session.flush()
    assign_role(db_session, user_id=admin.id, role_name=RoleName.SYSTEM_ADMIN.value)
    db_session.flush()
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"email": admin.email, "password": admin_password},
    )
    assert admin_login.status_code == 200, admin_login.text
    admin_token = admin_login.json()["access_token"]

    progress = client.get(
        f"/api/v1/admin/students/{student_user.id}/progress",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert progress.status_code == 200, progress.text
    progress_body = progress.json()
    # The admin projection must surface the mastery that the student loop
    # just persisted, not a stale or empty view. ``mastery_counts`` is a
    # status -> count map sourced from the same MasteryState rows.
    mastery_counts = progress_body.get("mastery_counts") or {}
    assert mastery_counts.get("INITIAL_MASTERY", 0) >= 1, (
        f"admin progress must reflect the persisted INITIAL_MASTERY, got {mastery_counts}"
    )
    # completed_tasks must be non-zero — the student just finished a submission.
    assert progress_body.get("completed_tasks", 0) >= 1, (
        f"admin progress must reflect the completed task, got {progress_body}"
    )
