"""Deterministic revision, code-run lifecycle, and assessment evidence policy."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.sandbox import (
    CodeRunMode,
    CodeRunStatus,
    SandboxResult,
    SandboxRunStatus,
    TestVisibility,
)
from app.evidence import record_evidence
from app.models import (
    CodeRevision,
    CodeRun,
    CodeRunStatusHistory,
    HintUsage,
    IdempotencyKey,
    OutboxEvent,
    TaskDefinition,
    TaskInstance,
    TaskVersion,
    TestResult,
)

ALLOWED_RUN_TRANSITIONS = {
    CodeRunStatus.QUEUED: {
        CodeRunStatus.RUNNING,
        CodeRunStatus.CANCELLED,
        CodeRunStatus.PLATFORM_ERROR,
    },
    CodeRunStatus.RUNNING: {
        CodeRunStatus.COMPLETED,
        CodeRunStatus.USER_ERROR,
        CodeRunStatus.PLATFORM_ERROR,
        CodeRunStatus.TIMEOUT,
        CodeRunStatus.CANCELLED,
    },
}
TERMINAL_RUN_STATUSES = frozenset(
    {
        CodeRunStatus.COMPLETED,
        CodeRunStatus.USER_ERROR,
        CodeRunStatus.PLATFORM_ERROR,
        CodeRunStatus.TIMEOUT,
        CodeRunStatus.CANCELLED,
    }
)


class InvalidCodeCommand(ValueError):
    pass


class ActiveCodeRunExists(InvalidCodeCommand):
    pass


class IllegalCodeRunTransition(InvalidCodeCommand):
    pass


def create_revision(
    db: Session,
    *,
    tenant_id: UUID,
    student_id: UUID,
    task_instance_id: UUID,
    source_code: str,
) -> CodeRevision:
    encoded = source_code.encode("utf-8")
    if not 1 <= len(encoded) <= 65_536:
        raise InvalidCodeCommand("source must contain 1..65536 UTF-8 bytes")

    task = db.scalar(
        select(TaskInstance)
        .where(
            TaskInstance.id == task_instance_id,
            TaskInstance.tenant_id == tenant_id,
            TaskInstance.student_id == student_id,
        )
        .with_for_update()
    )
    if task is None:
        raise InvalidCodeCommand("task does not belong to tenant and student")

    digest = hashlib.sha256(encoded).hexdigest()
    existing = db.scalar(
        select(CodeRevision).where(
            CodeRevision.tenant_id == tenant_id,
            CodeRevision.student_id == student_id,
            CodeRevision.task_instance_id == task_instance_id,
            CodeRevision.source_digest == digest,
        )
    )
    if existing is not None:
        return existing

    latest = db.scalar(
        select(CodeRevision)
        .where(CodeRevision.task_instance_id == task_instance_id)
        .order_by(CodeRevision.sequence.desc())
        .limit(1)
        .with_for_update()
    )
    revision = CodeRevision(
        tenant_id=tenant_id,
        student_id=student_id,
        task_instance_id=task_instance_id,
        sequence=(latest.sequence if latest else 0) + 1,
        parent_revision_id=latest.id if latest else None,
        source_digest=digest,
        source_code=source_code,
    )
    db.add(revision)
    db.flush()
    return revision


def outbox_for_run(run: CodeRun, *, event_type: str, trace_id: str) -> OutboxEvent:
    return OutboxEvent(
        tenant_id=run.tenant_id,
        event_type=event_type,
        event_id=f"evt_{uuid4().hex}",
        aggregate_type="code_run",
        aggregate_id=str(run.id),
        trace_id=trace_id,
        payload={
            "run_id": run.run_id,
            "task_instance_id": str(run.task_instance_id),
            "mode": run.mode.value,
            "status": run.status.value,
            "version": run.version,
            "policy_digest": run.policy_digest,
        },
    )


def reserve_code_run(
    db: Session,
    *,
    task: TaskInstance,
    revision: CodeRevision,
    idempotency: IdempotencyKey,
    mode: CodeRunMode,
    policy_snapshot: dict[str, Any],
    trace_id: str,
    now: datetime,
) -> CodeRun:
    locked_task = db.scalar(
        select(TaskInstance).where(TaskInstance.id == task.id).with_for_update()
    )
    if locked_task is None or locked_task.tenant_id != task.tenant_id:
        raise InvalidCodeCommand("task is not available")
    if revision.task_instance_id != task.id or revision.student_id != task.student_id:
        raise InvalidCodeCommand("revision does not belong to task")
    if idempotency.tenant_id != task.tenant_id or idempotency.user_id != task.student_id:
        raise InvalidCodeCommand("idempotency reservation is outside task scope")
    active = db.scalar(
        select(CodeRun)
        .where(
            CodeRun.task_instance_id == task.id,
            CodeRun.status.in_([CodeRunStatus.QUEUED, CodeRunStatus.RUNNING]),
        )
        .with_for_update()
    )
    if active is not None:
        raise ActiveCodeRunExists(f"task already has active run {active.run_id}")

    try:
        encoded_policy = json.dumps(
            policy_snapshot,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InvalidCodeCommand("policy snapshot must be canonical JSON") from exc
    run = CodeRun(
        run_id=f"run_{uuid4().hex}",
        tenant_id=task.tenant_id,
        student_id=task.student_id,
        task_instance_id=task.id,
        revision_id=revision.id,
        idempotency_key_id=idempotency.id,
        mode=mode,
        status=CodeRunStatus.QUEUED,
        policy_digest=hashlib.sha256(encoded_policy).hexdigest(),
        policy_snapshot=json.loads(encoded_policy),
        version=1,
        requested_at=now,
        deadline_at=now + timedelta(seconds=15),
    )
    db.add(run)
    db.flush()
    db.add(
        CodeRunStatusHistory(
            tenant_id=run.tenant_id,
            code_run_id=run.id,
            from_status=None,
            to_status=run.status,
            reason="RUN_RESERVED",
            trace_id=trace_id,
            created_at=now,
        )
    )
    db.add(outbox_for_run(run, event_type="CODE_RUN_QUEUED", trace_id=trace_id))
    db.flush()
    return run


def transition_code_run(
    db: Session,
    run: CodeRun,
    target: CodeRunStatus,
    *,
    reason: str,
    trace_id: str,
    now: datetime,
) -> CodeRun:
    current = run.status
    if target not in ALLOWED_RUN_TRANSITIONS.get(current, set()):
        raise IllegalCodeRunTransition(f"{current.value} -> {target.value}")
    run.status = target
    run.version += 1
    if target == CodeRunStatus.RUNNING:
        run.started_at = now
    if target in TERMINAL_RUN_STATUSES:
        run.completed_at = now
    db.add(
        CodeRunStatusHistory(
            tenant_id=run.tenant_id,
            code_run_id=run.id,
            from_status=current,
            to_status=target,
            reason=reason,
            trace_id=trace_id,
            created_at=now,
        )
    )
    db.add(outbox_for_run(run, event_type=f"CODE_RUN_{target.value}", trace_id=trace_id))
    db.flush()
    return run


def _bounded_utf8(value: str, limit: int, field: str) -> None:
    if len(value.encode("utf-8")) > limit:
        raise InvalidCodeCommand(f"sandbox {field} exceeds {limit} UTF-8 bytes")


def _validate_result_bounds(result: SandboxResult) -> None:
    _bounded_utf8(result.stdout, 32_768, "stdout")
    _bounded_utf8(result.stderr, 32_768, "stderr")
    for case in result.tests:
        if case.message is not None and len(case.message) > 2_000:
            raise InvalidCodeCommand("sandbox test message exceeds 2000 characters")
        _bounded_utf8(case.stdout, 32_768, "test stdout")
        _bounded_utf8(case.stderr, 32_768, "test stderr")


def _terminal_status(result: SandboxResult) -> CodeRunStatus:
    if result.platform_error is not None:
        return CodeRunStatus.PLATFORM_ERROR
    return {
        SandboxRunStatus.PASSED: CodeRunStatus.COMPLETED,
        SandboxRunStatus.FAILED: CodeRunStatus.USER_ERROR,
        SandboxRunStatus.ERROR: CodeRunStatus.USER_ERROR,
        SandboxRunStatus.TIMEOUT: CodeRunStatus.TIMEOUT,
        SandboxRunStatus.CANCELLED: CodeRunStatus.CANCELLED,
    }[result.status]


def assessment_facts_for_run(db: Session, run: CodeRun) -> dict[str, bool | int | float]:
    rows = list(
        db.scalars(
            select(TestResult).where(TestResult.code_run_id == run.id).order_by(TestResult.ordinal)
        )
    )
    hints = list(
        db.scalars(
            select(HintUsage)
            .where(HintUsage.task_instance_id == run.task_instance_id)
            .order_by(HintUsage.sequence)
        )
    )
    hidden_rows = [row for row in rows if row.visibility == TestVisibility.HIDDEN]
    hidden_transfer = [row for row in hidden_rows if row.transfer]
    independence = max(0.0, 1.0 - sum(hint.cost for hint in hints) / 100.0)
    transfer = (
        sum(1 for row in hidden_transfer if row.passed) / len(hidden_transfer)
        if hidden_transfer
        else float(bool(hidden_rows) and all(row.passed for row in hidden_rows))
    )
    return {
        "correct": run.status == CodeRunStatus.COMPLETED
        and bool(rows)
        and all(row.passed for row in rows),
        "hidden_tests_passed": bool(hidden_rows) and all(row.passed for row in hidden_rows),
        "hints_used": len(hints),
        "support_level": max((hint.level for hint in hints), default=0),
        "independence_score": round(independence, 10),
        "transfer_score": round(transfer, 10),
        "platform_error": run.status == CodeRunStatus.PLATFORM_ERROR,
    }


def finalize_code_run(
    db: Session,
    run_id: UUID,
    result: SandboxResult,
    *,
    now: datetime,
    trace_id: str = "sandbox-finalize",
) -> CodeRun:
    run = db.scalar(select(CodeRun).where(CodeRun.id == run_id).with_for_update())
    if run is None:
        raise InvalidCodeCommand("code run not found")
    if run.status in TERMINAL_RUN_STATUSES:
        return run
    if result.run_id != run.run_id:
        raise InvalidCodeCommand("sandbox result run_id mismatch")
    _validate_result_bounds(result)

    normalized = result.model_dump(mode="json")
    run.trace_frames = normalized.pop("trace_frames")
    run.result = normalized
    for ordinal, row in enumerate(result.tests, start=1):
        db.add(
            TestResult(
                tenant_id=run.tenant_id,
                code_run_id=run.id,
                ordinal=ordinal,
                case_id=row.case_id,
                display_name=row.display_name,
                visibility=row.visibility,
                comparison=row.comparison,
                transfer=row.transfer,
                passed=row.passed,
                message=row.message,
                stdout=row.stdout,
                stderr=row.stderr,
                stdout_truncated=row.stdout_truncated,
                stderr_truncated=row.stderr_truncated,
                duration_ms=row.duration_ms,
                created_at=now,
            )
        )
    db.flush()
    target = _terminal_status(result)
    transition_code_run(
        db,
        run,
        target,
        reason=f"SANDBOX_{result.status.value}",
        trace_id=trace_id,
        now=now,
    )

    if run.mode == CodeRunMode.SUBMIT and target not in {
        CodeRunStatus.PLATFORM_ERROR,
        CodeRunStatus.CANCELLED,
    }:
        task = db.get(TaskInstance, run.task_instance_id)
        version = db.get(TaskVersion, task.task_version_id) if task else None
        definition = db.get(TaskDefinition, version.definition_id) if version else None
        if task is None or definition is None:
            raise InvalidCodeCommand("task definition missing for assessment evidence")
        facts = assessment_facts_for_run(db, run)
        event_id = f"evt_assessment_{uuid4().hex}"
        event = record_evidence(
            db,
            tenant_id=run.tenant_id,
            student_id=run.student_id,
            event_id=event_id,
            event_type="ASSESSMENT_RECORDED",
            trace_id=trace_id,
            payload=facts,
            course_id=definition.course_id,
            node_id=definition.node_id,
            task_id=run.task_instance_id,
        )
        if event is None:
            raise InvalidCodeCommand("assessment evidence event collision")
        run.evidence_event_id = event.event_id
        db.flush()
    return run


def claim_stale_runs(db: Session, *, now: datetime, limit: int = 50) -> list[CodeRun]:
    statement = (
        select(CodeRun)
        .where(
            CodeRun.status.in_([CodeRunStatus.QUEUED, CodeRunStatus.RUNNING]),
            CodeRun.deadline_at <= now,
        )
        .order_by(CodeRun.deadline_at, CodeRun.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(db.scalars(statement))


def recover_stale_runs(
    db: Session, *, now: datetime, trace_id: str, limit: int = 50
) -> list[CodeRun]:
    recovered: list[CodeRun] = []
    for run in claim_stale_runs(db, now=now, limit=limit):
        result = SandboxResult.platform_failure(
            run_id=run.run_id,
            category="STALE_RUN",
            message="execution deadline elapsed before a durable result",
        )
        finalize_code_run(db, run.id, result, now=now, trace_id=trace_id)
        reservation = db.get(IdempotencyKey, run.idempotency_key_id)
        if reservation is not None:
            reservation.response_status = 503
            reservation.response_body = {
                "run_id": run.run_id,
                "status": CodeRunStatus.PLATFORM_ERROR.value,
            }
            db.flush()
        recovered.append(run)
    return recovered
