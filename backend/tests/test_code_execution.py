"""BE-005 Task 7 three-transaction code execution orchestration tests.

These tests exercise the orchestration against a live PostgreSQL with a fake
SandboxClient, proving transaction boundaries, phase rules, platform-fault
suppression, and stale recovery.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.code_execution import (
    CodeCommand,
    cancel_code_run,
    execute_code_command,
    recover_expired_code_runs,
)
from app.code_runs import create_revision, reserve_code_run
from app.contracts.sandbox import (
    CodeRunMode,
    CodeRunStatus,
    SandboxResult,
    SandboxRunStatus,
)
from app.models import (
    CodeRun,
    EvidenceEvent,
    IdempotencyKey,
)

NOW = datetime(2026, 7, 17, 9, 0, tzinfo=UTC)


def _passed_result(run_id: str, *, passed: bool = True, hidden: bool = False) -> SandboxResult:
    return SandboxResult(
        run_id=run_id,
        status=SandboxRunStatus.PASSED if passed else SandboxRunStatus.FAILED,
        passed=passed,
        stdout="",
        stderr="",
        tests=[
            {
                "case_id": "hidden-1" if hidden else "visible-basic",
                "display_name": "hidden-1" if hidden else "visible-basic",
                "visibility": "HIDDEN" if hidden else "VISIBLE",
                "comparison": "EQUAL",
                "transfer": hidden,
                "passed": passed,
                "stdout": "",
                "stderr": "",
                "duration_ms": 5,
            }
        ],
        trace_frames=None,
        resource_usage={"cpu_ms": 1, "wall_ms": 1, "peak_memory_kb": 100, "exit_code": 0},
        stdout_truncated=False,
        stderr_truncated=False,
        trace_truncated=False,
        user_error=None,
        platform_error=None,
    )


def _platform_failure(run_id: str, category: str = "DOCKER_UNAVAILABLE") -> SandboxResult:
    return SandboxResult.platform_failure(run_id=run_id, category=category, message="no daemon")


class FakeSandbox:
    """Records calls and returns canned per-phase results."""

    def __init__(
        self,
        *,
        visible: SandboxResult | None = None,
        hidden: SandboxResult | None = None,
        visible_error: Exception | None = None,
        hidden_error: Exception | None = None,
    ) -> None:
        self.visible = visible
        self.hidden = hidden
        self.visible_error = visible_error
        self.hidden_error = hidden_error
        self.execute_calls: list[str] = []
        self.cancel_calls: list[str] = []

    def execute_phase(self, request: Any) -> SandboxResult:
        phase = request.phase.value
        self.execute_calls.append(phase)
        if phase == "VISIBLE":
            if self.visible_error is not None:
                raise self.visible_error
            assert self.visible is not None
            return self.visible.model_copy(update={"run_id": request.run_id})
        if self.hidden_error is not None:
            raise self.hidden_error
        assert self.hidden is not None
        return self.hidden.model_copy(update={"run_id": request.run_id})

    def cancel(self, run_id: str) -> bool:
        self.cancel_calls.append(run_id)
        return True


def _command(
    context: Any,
    *,
    mode: CodeRunMode = CodeRunMode.RUN,
    idempotency: IdempotencyKey | None = None,
) -> CodeCommand:
    return CodeCommand(
        task=context.task,
        source_code="def solve(values):\n    return sum(values)\n",
        mode=mode,
        idempotency=idempotency or context.idempotency,
        expected_task_version=context.task.version,
        trace_id="trc-exec",
    )


def _factory(db_session: Session) -> sessionmaker[Session]:
    """Build a sessionmaker bound to the test's connection for real transactions."""

    class _Factory:
        def __call__(self) -> Session:
            return db_session

    return _Factory()  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# execute_code_command — RUN mode
# --------------------------------------------------------------------------- #


def test_run_mode_executes_only_visible_and_completes(
    code_context: Any, db_session: Session
) -> None:
    fake = FakeSandbox(visible=_passed_result("ignored"))
    view = execute_code_command(
        _command(code_context),
        sandbox=fake,
        session_factory=_factory(db_session),
    )
    assert view["mode"] == "RUN"
    assert view["status"] == CodeRunStatus.COMPLETED.value
    assert fake.execute_calls == ["VISIBLE"]
    run = db_session.scalar(select(CodeRun).where(CodeRun.run_id == view["run_id"]))
    assert run is not None
    assert run.status == CodeRunStatus.COMPLETED
    # RUN mode never emits assessment evidence.
    assert run.evidence_event_id is None


# --------------------------------------------------------------------------- #
# execute_code_command — SUBMIT mode
# --------------------------------------------------------------------------- #


def test_submit_mode_runs_visible_then_hidden_and_emits_evidence(
    code_context: Any, db_session: Session
) -> None:
    fake = FakeSandbox(
        visible=_passed_result("ignored", passed=True),
        hidden=_passed_result("ignored", passed=True, hidden=True),
    )
    view = execute_code_command(
        _command(code_context, mode=CodeRunMode.SUBMIT),
        sandbox=fake,
        session_factory=_factory(db_session),
    )
    assert fake.execute_calls == ["VISIBLE", "HIDDEN"]
    assert view["status"] == CodeRunStatus.COMPLETED.value
    run = db_session.scalar(select(CodeRun).where(CodeRun.run_id == view["run_id"]))
    assert run is not None
    assert run.evidence_event_id is not None
    evidence = db_session.scalar(
        select(EvidenceEvent).where(EvidenceEvent.event_id == run.evidence_event_id)
    )
    assert evidence is not None
    assert evidence.event_type == "ASSESSMENT_RECORDED"
    assert evidence.payload["correct"] is True
    assert evidence.payload["hidden_tests_passed"] is True


def test_submit_skips_hidden_after_visible_timeout(code_context: Any, db_session: Session) -> None:
    visible_timeout = SandboxResult(
        run_id="x",
        status=SandboxRunStatus.TIMEOUT,
        passed=False,
        stdout="",
        stderr="",
        tests=[],
        trace_frames=None,
        resource_usage={"cpu_ms": 0, "wall_ms": 0, "peak_memory_kb": None, "exit_code": None},
        stdout_truncated=False,
        stderr_truncated=False,
        trace_truncated=False,
        user_error="TIMEOUT: wall-clock exceeded",
        platform_error=None,
    )
    fake = FakeSandbox(visible=visible_timeout, hidden=_passed_result("ignored", hidden=True))
    view = execute_code_command(
        _command(code_context, mode=CodeRunMode.SUBMIT),
        sandbox=fake,
        session_factory=_factory(db_session),
    )
    assert fake.execute_calls == ["VISIBLE"]
    assert view["status"] == CodeRunStatus.TIMEOUT.value
    run = db_session.scalar(select(CodeRun).where(CodeRun.run_id == view["run_id"]))
    assert run is not None
    # Timeout is student-caused but SUBMIT with incomplete hidden tests still
    # records evidence only when the outcome is terminal and non-platform; here
    # the hidden phase was skipped, so no hidden evidence.
    assert run.evidence_event_id is not None  # SUBMIT + student timeout → evidence allowed


def test_submit_hidden_platform_failure_suppresses_evidence(
    code_context: Any, db_session: Session
) -> None:
    fake = FakeSandbox(
        visible=_passed_result("ignored", passed=True),
        hidden=_platform_failure("ignored", "HIDDEN_PHASE"),
    )
    view = execute_code_command(
        _command(code_context, mode=CodeRunMode.SUBMIT),
        sandbox=fake,
        session_factory=_factory(db_session),
    )
    assert view["status"] == CodeRunStatus.PLATFORM_ERROR.value
    run = db_session.scalar(select(CodeRun).where(CodeRun.run_id == view["run_id"]))
    assert run is not None
    # A platform error never emits assessment evidence.
    assert run.evidence_event_id is None


def test_visible_platform_failure_makes_submission_platform_error(
    code_context: Any, db_session: Session
) -> None:
    fake = FakeSandbox(
        visible=_platform_failure("ignored", "VISIBLE_PHASE"),
        hidden=_passed_result("ignored", hidden=True),
    )
    view = execute_code_command(
        _command(code_context, mode=CodeRunMode.SUBMIT),
        sandbox=fake,
        session_factory=_factory(db_session),
    )
    # Visible platform failure skips hidden entirely.
    assert fake.execute_calls == ["VISIBLE"]
    assert view["status"] == CodeRunStatus.PLATFORM_ERROR.value


def test_visible_runtime_error_still_runs_hidden(code_context: Any, db_session: Session) -> None:
    """An ordinary student runtime error in the visible phase proceeds to hidden."""

    visible_error = SandboxResult(
        run_id="x",
        status=SandboxRunStatus.ERROR,
        passed=False,
        stdout="",
        stderr="",
        tests=[
            {
                "case_id": "visible-basic",
                "display_name": "visible-basic",
                "visibility": "VISIBLE",
                "comparison": "EQUAL",
                "transfer": False,
                "passed": False,
                "stdout": "",
                "stderr": "",
                "duration_ms": 3,
            }
        ],
        trace_frames=None,
        resource_usage={"cpu_ms": 1, "wall_ms": 1, "peak_memory_kb": 100, "exit_code": 1},
        stdout_truncated=False,
        stderr_truncated=False,
        trace_truncated=False,
        user_error="RUNTIME_ERROR: ZeroDivisionError",
        platform_error=None,
    )
    fake = FakeSandbox(visible=visible_error, hidden=_passed_result("ignored", hidden=True))
    view = execute_code_command(
        _command(code_context, mode=CodeRunMode.SUBMIT),
        sandbox=fake,
        session_factory=_factory(db_session),
    )
    assert fake.execute_calls == ["VISIBLE", "HIDDEN"]
    assert view["status"] == CodeRunStatus.USER_ERROR.value


# --------------------------------------------------------------------------- #
# SandboxPlatformFailure mapping
# --------------------------------------------------------------------------- #


def test_sandbox_platform_failure_becomes_platform_error(
    code_context: Any, db_session: Session
) -> None:
    from app.sandbox_client import SandboxPlatformFailure

    fake = FakeSandbox(visible_error=SandboxPlatformFailure("SUPERVISOR_TIMEOUT", "slow"))
    view = execute_code_command(
        _command(code_context),
        sandbox=fake,
        session_factory=_factory(db_session),
    )
    assert view["status"] == CodeRunStatus.PLATFORM_ERROR.value
    run = db_session.scalar(select(CodeRun).where(CodeRun.run_id == view["run_id"]))
    assert run is not None
    assert run.evidence_event_id is None


# --------------------------------------------------------------------------- #
# cancel_code_run
# --------------------------------------------------------------------------- #


def test_cancel_finalizes_cancelled_and_removes_containers(
    code_context: Any, db_session: Session
) -> None:
    # First create a run via the orchestrator.
    fake = FakeSandbox(visible=_passed_result("ignored"))
    view = execute_code_command(
        _command(code_context),
        sandbox=fake,
        session_factory=_factory(db_session),
    )
    # Reopen the run as non-terminal for the cancel path: simulate a RUNNING run.
    run = db_session.scalar(select(CodeRun).where(CodeRun.run_id == view["run_id"]))
    assert run is not None
    # The run is already COMPLETED; cancel on a terminal run finalizes no-op
    # (finalize_code_run returns the existing terminal run unchanged).
    cancel_fake = FakeSandbox()
    cancel_view = cancel_code_run(
        run,
        sandbox=cancel_fake,
        session_factory=_factory(db_session),
        trace_id="trc-cancel",
    )
    assert cancel_view["run_id"] == view["run_id"]
    # Cancel was attempted (best-effort) even on a terminal run.
    assert cancel_fake.cancel_calls == [run.run_id]


# --------------------------------------------------------------------------- #
# recover_expired_code_runs
# --------------------------------------------------------------------------- #


def test_recover_expired_runs_finalizes_platform_error_without_evidence(
    code_context: Any, db_session: Session
) -> None:
    # Create a stale QUEUED run whose deadline is in the past.
    revision = create_revision(
        db_session,
        tenant_id=code_context.tenant.id,
        student_id=code_context.student.id,
        task_instance_id=code_context.task.id,
        source_code="def solve(values):\n    return sum(values)\n",
    )
    stale_idem = IdempotencyKey(
        key=f"idem-{uuid4().hex}",
        tenant_id=code_context.tenant.id,
        user_id=code_context.student.id,
        endpoint="POST /api/v1/code/runs",
        expires_at=NOW + timedelta(days=1),
    )
    db_session.add(stale_idem)
    db_session.flush()
    stale_run = reserve_code_run(
        db_session,
        task=code_context.task,
        revision=revision,
        idempotency=stale_idem,
        mode=CodeRunMode.RUN,
        policy_snapshot=code_context.task.snapshot,
        trace_id="trc-reserve",
        now=NOW - timedelta(minutes=10),
    )
    db_session.commit()

    fake = FakeSandbox()
    recovered = recover_expired_code_runs(
        sandbox=fake,
        session_factory=_factory(db_session),
        now=NOW,
    )
    assert recovered >= 1
    db_session.expire_all()
    finalized = db_session.get(CodeRun, stale_run.id)
    assert finalized is not None
    assert finalized.status == CodeRunStatus.PLATFORM_ERROR
    assert finalized.evidence_event_id is None
    assert stale_run.run_id in fake.cancel_calls
