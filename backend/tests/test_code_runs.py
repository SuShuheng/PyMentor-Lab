"""BE-005 deterministic code revision, lifecycle, and evidence policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.code_runs import (
    ActiveCodeRunExists,
    IllegalCodeRunTransition,
    InvalidCodeCommand,
    assessment_facts_for_run,
    claim_stale_runs,
    create_revision,
    finalize_code_run,
    recover_stale_runs,
    reserve_code_run,
    transition_code_run,
)
from app.contracts.sandbox import (
    CodeRunMode,
    CodeRunStatus,
    SandboxComparison,
    SandboxResourceUsage,
    SandboxResult,
    SandboxRunStatus,
    SandboxTestCaseResult,
)
from app.contracts.sandbox import (
    TestVisibility as Visibility,
)
from app.models import (
    CodeRun,
    CodeRunStatusHistory,
    EvidenceEvent,
    HintSource,
    HintUsage,
    IdempotencyKey,
    OutboxEvent,
    TaskDefinition,
    TaskInstance,
    TaskInstanceStatus,
    TaskVersion,
    Tenant,
    User,
    UserStatus,
)
from app.models import (
    TestResult as CodeTestResult,
)

NOW = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
COURSE_ID = UUID("00000000-0000-0000-0000-000000000501")
NODE_ID = UUID("00000000-0000-0000-0000-000000000502")


@dataclass(slots=True)
class CodeContext:
    tenant: Tenant
    student: User
    task: TaskInstance
    idempotency: IdempotencyKey


def _snapshot() -> dict[str, object]:
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
        "mastery_policy": {},
        "resource_versions": {},
        "scenario_key": "sum-v1",
    }


@pytest.fixture()
def code_context(db_session: Session) -> CodeContext:
    suffix = uuid4().hex
    tenant = Tenant(slug=f"code-{suffix}", name="Code Evidence")
    db_session.add(tenant)
    db_session.flush()
    student = User(
        tenant_id=tenant.id,
        email=f"code-{suffix}@example.com",
        password_hash="not-used",
        status=UserStatus.ACTIVE,
    )
    db_session.add(student)
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
    version = TaskVersion(
        tenant_id=tenant.id,
        definition_id=definition.id,
        version=1,
        snapshot=snapshot,
        snapshot_digest="a" * 64,
        scenario_key="sum-v1",
        published=True,
        published_at=NOW,
    )
    db_session.add(version)
    db_session.flush()
    task = TaskInstance(
        tenant_id=tenant.id,
        student_id=student.id,
        task_version_id=version.id,
        active_key=f"code-{suffix}",
        status=TaskInstanceStatus.ACTIVE,
        snapshot=snapshot,
        snapshot_digest=version.snapshot_digest,
        version=1,
    )
    idempotency = IdempotencyKey(
        key=f"idem-{suffix}",
        tenant_id=tenant.id,
        user_id=student.id,
        endpoint="POST /api/v1/code/runs",
        expires_at=NOW + timedelta(days=1),
    )
    db_session.add_all([task, idempotency])
    db_session.flush()
    return CodeContext(tenant, student, task, idempotency)


def _new_idempotency(db: Session, context: CodeContext) -> IdempotencyKey:
    record = IdempotencyKey(
        key=f"idem-{uuid4().hex}",
        tenant_id=context.tenant.id,
        user_id=context.student.id,
        endpoint="POST /api/v1/code/runs",
        expires_at=NOW + timedelta(days=1),
    )
    db.add(record)
    db.flush()
    return record


def _reserve(db: Session, context: CodeContext, *, mode: CodeRunMode = CodeRunMode.RUN) -> CodeRun:
    revision = create_revision(
        db,
        tenant_id=context.tenant.id,
        student_id=context.student.id,
        task_instance_id=context.task.id,
        source_code="def solve(values):\n    return sum(values)\n",
    )
    return reserve_code_run(
        db,
        task=context.task,
        revision=revision,
        idempotency=context.idempotency,
        mode=mode,
        policy_snapshot=context.task.snapshot,
        trace_id="trc-reserve",
        now=NOW,
    )


def _case(
    case_id: str,
    visibility: Visibility,
    *,
    transfer: bool,
    passed: bool = True,
) -> SandboxTestCaseResult:
    return SandboxTestCaseResult(
        case_id=case_id,
        display_name=case_id,
        visibility=visibility,
        comparison=SandboxComparison.EQUAL,
        transfer=transfer,
        passed=passed,
        message=None,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=2,
    )


def _result(run_id: str) -> SandboxResult:
    return SandboxResult(
        run_id=run_id,
        status=SandboxRunStatus.PASSED,
        passed=True,
        stdout="",
        stderr="",
        tests=[
            _case("visible-basic", Visibility.VISIBLE, transfer=False),
            _case("hidden-transfer", Visibility.HIDDEN, transfer=True),
        ],
        trace_frames=None,
        resource_usage=SandboxResourceUsage(
            cpu_ms=10, wall_ms=20, peak_memory_kb=1024, exit_code=0
        ),
        stdout_truncated=False,
        stderr_truncated=False,
        trace_truncated=False,
        user_error=None,
        platform_error=None,
    )


def test_revision_digest_reuse_sequence_and_utf8_bound(
    db_session: Session, code_context: CodeContext
) -> None:
    first = create_revision(
        db_session,
        tenant_id=code_context.tenant.id,
        student_id=code_context.student.id,
        task_instance_id=code_context.task.id,
        source_code="print('你好')",
    )
    replay = create_revision(
        db_session,
        tenant_id=code_context.tenant.id,
        student_id=code_context.student.id,
        task_instance_id=code_context.task.id,
        source_code="print('你好')",
    )
    second = create_revision(
        db_session,
        tenant_id=code_context.tenant.id,
        student_id=code_context.student.id,
        task_instance_id=code_context.task.id,
        source_code="print('再见')",
    )
    assert replay.id == first.id
    assert second.sequence == 2
    assert second.parent_revision_id == first.id
    with pytest.raises(InvalidCodeCommand, match="UTF-8 bytes"):
        create_revision(
            db_session,
            tenant_id=code_context.tenant.id,
            student_id=code_context.student.id,
            task_instance_id=code_context.task.id,
            source_code="界" * 22_000,
        )


def test_reserve_and_transition_write_history_and_safe_outbox(
    db_session: Session, code_context: CodeContext
) -> None:
    run = _reserve(db_session, code_context)
    transition_code_run(
        db_session,
        run,
        CodeRunStatus.RUNNING,
        reason="SUPERVISOR_ACCEPTED",
        trace_id="trc-running",
        now=NOW + timedelta(seconds=1),
    )
    transition_code_run(
        db_session,
        run,
        CodeRunStatus.COMPLETED,
        reason="SANDBOX_PASSED",
        trace_id="trc-complete",
        now=NOW + timedelta(seconds=2),
    )
    assert run.version == 3
    assert run.started_at == NOW + timedelta(seconds=1)
    assert run.completed_at == NOW + timedelta(seconds=2)
    history = list(
        db_session.scalars(
            select(CodeRunStatusHistory).where(CodeRunStatusHistory.code_run_id == run.id)
        )
    )
    assert [row.to_status for row in history] == [
        CodeRunStatus.QUEUED,
        CodeRunStatus.RUNNING,
        CodeRunStatus.COMPLETED,
    ]
    events = list(
        db_session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == str(run.id)))
    )
    assert len(events) == 3
    assert all("source_code" not in event.payload for event in events)
    with pytest.raises(IllegalCodeRunTransition, match="COMPLETED -> RUNNING"):
        transition_code_run(
            db_session,
            run,
            CodeRunStatus.RUNNING,
            reason="INVALID",
            trace_id="trc-invalid",
            now=NOW + timedelta(seconds=3),
        )


def test_only_one_active_run_is_reserved(db_session: Session, code_context: CodeContext) -> None:
    first = _reserve(db_session, code_context)
    revision = create_revision(
        db_session,
        tenant_id=code_context.tenant.id,
        student_id=code_context.student.id,
        task_instance_id=code_context.task.id,
        source_code="print('different')",
    )
    with pytest.raises(ActiveCodeRunExists):
        reserve_code_run(
            db_session,
            task=code_context.task,
            revision=revision,
            idempotency=_new_idempotency(db_session, code_context),
            mode=CodeRunMode.TRACE,
            policy_snapshot=code_context.task.snapshot,
            trace_id="trc-second",
            now=NOW,
        )
    assert first.status == CodeRunStatus.QUEUED


def test_assessment_facts_include_hint_cost_and_transfer(
    db_session: Session, code_context: CodeContext
) -> None:
    run = _reserve(db_session, code_context, mode=CodeRunMode.SUBMIT)
    transition_code_run(
        db_session,
        run,
        CodeRunStatus.RUNNING,
        reason="STARTED",
        trace_id="trc-started",
        now=NOW + timedelta(seconds=1),
    )
    db_session.add_all(
        [
            HintUsage(
                tenant_id=code_context.tenant.id,
                student_id=code_context.student.id,
                task_instance_id=code_context.task.id,
                revision_id=run.revision_id,
                sequence=1,
                hint_key="inspect-input",
                level=1,
                cost=10,
                content="Inspect the input shape.",
                source=HintSource.STATIC,
            ),
            HintUsage(
                tenant_id=code_context.tenant.id,
                student_id=code_context.student.id,
                task_instance_id=code_context.task.id,
                revision_id=run.revision_id,
                sequence=2,
                hint_key="check-bound",
                level=2,
                cost=25,
                content="Check the boundary.",
                source=HintSource.STATIC,
            ),
        ]
    )
    db_session.flush()
    finalized = finalize_code_run(
        db_session, run.id, _result(run.run_id), now=NOW + timedelta(seconds=2)
    )
    facts = assessment_facts_for_run(db_session, finalized)
    assert facts == {
        "correct": True,
        "hidden_tests_passed": True,
        "hints_used": 2,
        "support_level": 2,
        "independence_score": 0.65,
        "transfer_score": 1.0,
        "platform_error": False,
    }
    assert finalized.status == CodeRunStatus.COMPLETED
    assert finalized.evidence_event_id is not None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(CodeTestResult)
            .where(CodeTestResult.code_run_id == run.id)
        )
        == 2
    )


def test_platform_error_never_creates_assessment_evidence(
    db_session: Session, code_context: CodeContext
) -> None:
    run = _reserve(db_session, code_context, mode=CodeRunMode.SUBMIT)
    result = SandboxResult.platform_failure(
        run_id=run.run_id,
        category="ENGINE_UNAVAILABLE",
        message="runner unavailable",
    )
    finalized = finalize_code_run(db_session, run.id, result, now=NOW)
    assert finalized.status == CodeRunStatus.PLATFORM_ERROR
    assert finalized.evidence_event_id is None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(EvidenceEvent)
            .where(
                EvidenceEvent.task_id == run.task_instance_id,
                EvidenceEvent.event_type == "ASSESSMENT_RECORDED",
            )
        )
        == 0
    )


def test_stale_recovery_marks_active_run_and_completes_idempotency(
    db_session: Session, code_context: CodeContext
) -> None:
    run = _reserve(db_session, code_context)
    run.deadline_at = NOW - timedelta(seconds=1)
    db_session.flush()
    assert [row.id for row in claim_stale_runs(db_session, now=NOW)] == [run.id]
    recovered = recover_stale_runs(db_session, now=NOW, trace_id="trc-recovery")
    assert [row.id for row in recovered] == [run.id]
    assert run.status == CodeRunStatus.PLATFORM_ERROR
    assert code_context.idempotency.response_status == 503
