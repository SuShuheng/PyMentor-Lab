"""Three-transaction orchestration of isolated code execution (BE-005 Task 7).

The API command boundary delegates here to run student code through the signed
Sandbox Supervisor while preserving the design's transaction rules:

1. **Reserve** (transaction 1): create/reuse the revision, persist a ``QUEUED``
   run with audit + Outbox, and commit before any external call.
2. **Mark running + execute** (transaction 2): row-lock the run, move it to
   ``RUNNING``, commit, then call the Supervisor *with no database transaction
   open*. Visible runs execute visible cases; submissions additionally run a
   hidden phase in a separate container unless skipped by a hard failure.
3. **Finalize** (transaction 3): persist the normalized result, transition to
   the terminal status, emit assessment evidence for student-caused submissions,
   and complete the linked idempotency response.

A platform failure in either phase makes the whole submission a platform error
and suppresses assessment evidence. Cancellation and stale recovery reuse the
same finalize path with bounded platform-failure results.

See ``docs/superpowers/specs/2026-07-17-be-005-sandbox-code-evidence-design.md``
§Formal Run State Machine and §Error Classification.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.code_runs import (
    ActiveCodeRunExists,
    InvalidCodeCommand,
    claim_stale_runs,
    create_revision,
    finalize_code_run,
    reserve_code_run,
    transition_code_run,
)
from app.contracts.sandbox import (
    CodeRunMode,
    CodeRunStatus,
    SandboxExecutionPolicy,
    SandboxExecutionRequest,
    SandboxPhase,
    SandboxResult,
    SandboxRunStatus,
)
from app.db import SessionLocal
from app.models import CodeRun, IdempotencyKey, TaskInstance
from app.sandbox_client import (
    SandboxPlatformFailure,
    platform_failure_result,
)
from app.task_policy import CompiledTaskPolicy, parse_task_policy
from app.uow import SqlAlchemyUnitOfWork

SANDBOX_TRACE_ID = "sandbox-execution"

# Default execution policy used when a task snapshot does not carry an explicit
# one. The Supervisor enforces absolute ceilings; these stay inside them.
DEFAULT_POLICY: dict[str, int] = {
    "timeout_ms": 5_000,
    "memory_mb": 128,
    "pids_limit": 32,
    "output_limit_bytes": 32_768,
    "test_limit": 256,
    "trace_frame_limit": 200,
}


class _ExecutorLike(Protocol):
    """Minimal interface the orchestrator needs from a sandbox client."""

    def execute_phase(self, request: SandboxExecutionRequest) -> SandboxResult: ...

    def cancel(self, run_id: str) -> bool: ...


@dataclass(slots=True)
class CodeCommand:
    """A validated code command bound to a student-scoped task instance."""

    task: TaskInstance
    source_code: str
    mode: CodeRunMode
    idempotency: IdempotencyKey
    expected_task_version: int
    trace_enabled: bool = False
    trace_id: str = SANDBOX_TRACE_ID


@dataclass(frozen=True, slots=True)
class ReservedRun:
    """Identity of a reserved run, detached from any session.

    Carries only the DB primary key and the opaque run_id the Supervisor and
    finalize path need; the ORM object stays inside its transaction.
    """

    id: UUID
    run_id: str


def _now() -> datetime:
    return datetime.now(UTC)


def _policy_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the execution policy snapshot, falling back to safe defaults."""

    explicit = snapshot.get("sandbox_policy")
    if isinstance(explicit, dict):
        merged = {**DEFAULT_POLICY, **explicit}
        return merged
    return {**DEFAULT_POLICY}


def _execution_request(
    command: CodeCommand,
    *,
    policy: CompiledTaskPolicy,
    snapshot: dict[str, Any],
    phase_cases: list[Any],
    phase: SandboxPhase,
    run_id: str,
) -> SandboxExecutionRequest:
    """Build a per-phase execution request from the command and policy."""

    policy_snapshot = _policy_snapshot(snapshot)
    return SandboxExecutionRequest(
        protocol_version="1",
        request_id=f"{run_id}-{phase.value.lower()}",
        run_id=run_id,
        trace_id=command.trace_id,
        source_code=command.source_code,
        entrypoint=policy.tests.entrypoint,
        cases=phase_cases,
        allowed_imports=list(policy.tests.allowed_imports),
        phase=phase,
        policy=SandboxExecutionPolicy.model_validate(policy_snapshot),
        trace_enabled=command.trace_enabled,
    )


def _should_run_hidden(visible_result: SandboxResult) -> bool:
    """Run the hidden phase unless the visible phase hard-failed.

    A platform error, timeout, or cancellation skips the hidden phase because
    the hidden result would be incomplete or the student already hit a hard
    wall. Failed comparisons (FAILED) and ordinary student runtime errors
    (ERROR with no platform error) still proceed so a student can see hidden
    feedback after a visible runtime error.
    """

    if visible_result.platform_error is not None:
        return False
    return visible_result.status not in {SandboxRunStatus.TIMEOUT, SandboxRunStatus.CANCELLED}


def _combine_results(
    visible: SandboxResult,
    hidden: SandboxResult | None,
    *,
    run_id: str,
    mode: CodeRunMode,
) -> SandboxResult:
    """Merge visible and hidden phase results into one bounded result.

    A platform error in either phase makes the whole submission a platform
    error so assessment evidence is suppressed (the hidden result is incomplete).
    """

    if visible.platform_error is not None:
        return platform_failure_result(run_id, "VISIBLE_PHASE", visible.platform_error)
    if hidden is not None and hidden.platform_error is not None:
        return platform_failure_result(run_id, "HIDDEN_PHASE", hidden.platform_error)
    if hidden is None or mode != CodeRunMode.SUBMIT:
        return visible
    # Both phases succeeded at the protocol level; merge test rows.
    merged_tests = [*visible.tests, *hidden.tests]
    all_passed = visible.passed and hidden.passed and all(t.passed for t in merged_tests)
    status = (
        SandboxRunStatus.PASSED
        if all_passed
        else (
            SandboxRunStatus.FAILED if visible.status == SandboxRunStatus.PASSED else visible.status
        )
    )
    return SandboxResult(
        run_id=run_id,
        status=status,
        passed=all_passed,
        stdout=visible.stdout,
        stderr=visible.stderr,
        tests=merged_tests,
        trace_frames=visible.trace_frames,
        resource_usage=visible.resource_usage,
        stdout_truncated=visible.stdout_truncated,
        stderr_truncated=visible.stderr_truncated,
        trace_truncated=visible.trace_truncated,
        user_error=visible.user_error,
        platform_error=None,
    )


def _view_from_run(run: CodeRun) -> dict[str, Any]:
    """Build the public ``CodeRunView`` projection (no source/hidden policy)."""

    from sqlalchemy.orm import object_session

    from app.models import CodeRevision

    session = object_session(run)
    revision = session.get(CodeRevision, run.revision_id) if session else None
    revision_view = {
        "id": str(run.revision_id),
        "sequence": revision.sequence if revision else 1,
        "source_digest": revision.source_digest if revision else "0" * 64,
        "created_at": (revision.created_at if revision else run.requested_at).isoformat(),
    }
    return {
        "run_id": run.run_id,
        "task_instance_id": str(run.task_instance_id),
        "mode": run.mode.value,
        "status": run.status.value,
        "version": run.version,
        "revision": revision_view,
        "result": run.result,
        "evidence_event_id": run.evidence_event_id,
        "requested_at": run.requested_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _reserve_transaction(
    command: CodeCommand,
    *,
    session_factory: sessionmaker[Session],
    snapshot: dict[str, Any],
) -> ReservedRun:
    """Transaction 1: create revision + QUEUED run + audit + Outbox, commit.

    Returns a :class:`ReservedRun` carrying only the identity the caller needs;
    the ORM object stays inside its committed transaction.
    """

    now = _now()
    with SqlAlchemyUnitOfWork(session_factory) as uow:
        db = uow.session
        assert db is not None
        revision = create_revision(
            db,
            tenant_id=command.task.tenant_id,
            student_id=command.task.student_id,
            task_instance_id=command.task.id,
            source_code=command.source_code,
        )
        run = reserve_code_run(
            db,
            task=command.task,
            revision=revision,
            idempotency=command.idempotency,
            mode=command.mode,
            policy_snapshot=_policy_snapshot(snapshot),
            trace_id=command.trace_id,
            now=now,
        )
        db.flush()
        reserved = ReservedRun(id=run.id, run_id=run.run_id)
        uow.commit()
        return reserved


def _mark_running_transaction(
    run_id: UUID,
    *,
    session_factory: sessionmaker[Session],
    trace_id: str,
) -> None:
    """Transaction 2a: row-lock, move to RUNNING, commit before external call."""

    from sqlalchemy import select

    from app.models import CodeRun as CodeRunModel

    now = _now()
    with SqlAlchemyUnitOfWork(session_factory) as uow:
        db = uow.session
        assert db is not None
        run = db.scalar(select(CodeRunModel).where(CodeRunModel.id == run_id).with_for_update())
        if run is None:
            raise InvalidCodeCommand("code run not found during RUNNING transition")
        transition_code_run(
            db,
            run,
            CodeRunStatus.RUNNING,
            reason="SUPERVISOR_INVOKED",
            trace_id=trace_id,
            now=now,
        )
        db.flush()
        uow.commit()


def execute_code_command(
    command: CodeCommand,
    *,
    sandbox: _ExecutorLike,
    session_factory: sessionmaker[Session] = SessionLocal,
) -> dict[str, Any]:
    """Run the three-transaction orchestration and return a CodeRunView dict.

    The Supervisor is called only between committed transactions, never with a
    database transaction open. Platform faults become bounded platform-failure
    results so mastery is never reduced by infrastructure.
    """

    # Capture the snapshot before any transaction so commit/expunge inside the
    # orchestrator's own sessions never expires the API request's task object.
    snapshot = dict(command.task.snapshot)
    policy = parse_task_policy(snapshot)
    run = _reserve_transaction(command, session_factory=session_factory, snapshot=snapshot)
    try:
        _mark_running_transaction(
            run.id, session_factory=session_factory, trace_id=command.trace_id
        )
    except (InvalidCodeCommand, ActiveCodeRunExists) as exc:
        result = platform_failure_result(run.run_id, "RUNNING_TRANSITION", str(exc)[:200])
        return _finalize_view(
            run.id,
            result,
            session_factory=session_factory,
            trace_id=command.trace_id,
        )

    visible_result = _run_phase(
        run.run_id,
        command=command,
        policy=policy,
        snapshot=snapshot,
        phase=SandboxPhase.VISIBLE,
        phase_cases=list(policy.tests.visible),
        sandbox=sandbox,
    )
    hidden_result: SandboxResult | None = None
    if command.mode == CodeRunMode.SUBMIT and _should_run_hidden(visible_result):
        hidden_result = _run_phase(
            run.run_id,
            command=command,
            policy=policy,
            snapshot=snapshot,
            phase=SandboxPhase.HIDDEN,
            phase_cases=list(policy.tests.hidden),
            sandbox=sandbox,
        )

    combined = _combine_results(visible_result, hidden_result, run_id=run.run_id, mode=command.mode)
    return _finalize_view(
        run.id,
        combined,
        session_factory=session_factory,
        trace_id=command.trace_id,
    )


def _run_phase(
    run_id: str,
    *,
    command: CodeCommand,
    policy: CompiledTaskPolicy,
    snapshot: dict[str, Any],
    phase: SandboxPhase,
    phase_cases: list[Any],
    sandbox: _ExecutorLike,
) -> SandboxResult:
    """Invoke the Supervisor for one phase, mapping platform faults."""

    request = _execution_request(
        command,
        policy=policy,
        snapshot=snapshot,
        phase_cases=phase_cases,
        phase=phase,
        run_id=run_id,
    )
    try:
        return sandbox.execute_phase(request)
    except SandboxPlatformFailure as exc:
        return platform_failure_result(run_id, exc.category, exc.message)


def _finalize_view(
    run_id: UUID,
    result: SandboxResult,
    *,
    session_factory: sessionmaker[Session],
    trace_id: str,
) -> dict[str, Any]:
    """Transaction 3: finalize the run and return the public view."""

    now = _now()
    with SqlAlchemyUnitOfWork(session_factory) as uow:
        db = uow.session
        assert db is not None
        run = finalize_code_run(db, run_id, result, now=now, trace_id=trace_id)
        uow.commit()
        view = _view_from_run(run)
        return view


def cancel_code_run(
    run: CodeRun,
    *,
    sandbox: _ExecutorLike,
    session_factory: sessionmaker[Session] = SessionLocal,
    trace_id: str = SANDBOX_TRACE_ID,
) -> dict[str, Any]:
    """Cancel a non-terminal run: kill labeled containers, then commit CANCELLED.

    Cancellation is idempotent. A terminal non-cancelled run returns CONFLICT
    (handled by the caller); here we finalize CANCELLED and ask the Supervisor
    to remove any labeled containers.
    """

    now = _now()
    # Best-effort container cleanup; a cleanup fault must not block the formal
    # CANCELLED transition (the recovery service re-attempts removal).
    with contextlib.suppress(SandboxPlatformFailure):
        sandbox.cancel(run.run_id)
    result = platform_failure_result(run.run_id, "CANCELLED", "cancelled by request")
    with SqlAlchemyUnitOfWork(session_factory) as uow:
        db = uow.session
        assert db is not None
        finalized = finalize_code_run(db, run.id, result, now=now, trace_id=trace_id)
        uow.commit()
        return _view_from_run(finalized)


def recover_expired_code_runs(
    *,
    sandbox: _ExecutorLike,
    session_factory: sessionmaker[Session] = SessionLocal,
    now: datetime | None = None,
    limit: int = 50,
) -> int:
    """Find stale non-terminal runs, clean up, and finalize PLATFORM_ERROR.

    Replay-safe: never produces assessment evidence. Container cleanup is
    best-effort; a cleanup fault is security-logged but does not block the
    formal PLATFORM_ERROR transition.
    """

    current = now or _now()
    recovered = 0
    with SqlAlchemyUnitOfWork(session_factory) as select_uow:
        db = select_uow.session
        assert db is not None
        stale = claim_stale_runs(db, now=current, limit=limit)

    for run in stale:
        with contextlib.suppress(SandboxPlatformFailure):
            sandbox.cancel(run.run_id)
        result = platform_failure_result(
            run.run_id, "STALE_RECOVERY", "run exceeded deadline without completing"
        )
        with SqlAlchemyUnitOfWork(session_factory) as uow:
            db = uow.session
            assert db is not None
            finalize_code_run(db, run.id, result, now=current, trace_id=SANDBOX_TRACE_ID)
            uow.commit()
        recovered += 1
    return recovered


__all__ = [
    "CodeCommand",
    "cancel_code_run",
    "execute_code_command",
    "recover_expired_code_runs",
]
