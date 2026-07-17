"""Idempotent ingestion of redacted BE-006 worker audit envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.worker import AgentAuditEnvelope, AgentProposalEnvelope
from app.models.agent import AgentDefinition, AgentRun, AgentToolCall

_SAFE_DETAIL_KEYS = frozenset(
    {
        "status",
        "code",
        "latency_ms",
        "input_bytes",
        "output_bytes",
        "argument_digest",
        "result_digest",
        "retry_count",
        "fallback",
    }
)
_TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED_FINAL", "CANCELLED"})
_INPUT_EVENTS = frozenset({"RUN_STARTED", "NODE_STARTED", "TOOL_STARTED", "REPLAY_STARTED"})
_TOOL_EVENTS = frozenset({"TOOL_STARTED", "TOOL_COMPLETED", "TOOL_FAILED"})


@dataclass(frozen=True, slots=True)
class AgentReplayMetadata:
    agent_run_id: str
    event_id: str
    thread_id: str
    checkpoint_id: str


def _uuid(value: str, field: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a UUID for persistence") from exc


def _safe_detail(event: AgentAuditEnvelope) -> dict[str, object]:
    detail = event.detail.model_dump(mode="json", exclude_none=True)
    if not set(detail).issubset(_SAFE_DETAIL_KEYS):
        raise ValueError("agent audit detail contains non-redacted fields")
    return detail


def _load_run(db: Session, event_id: str) -> AgentRun | None:
    return db.scalar(select(AgentRun).where(AgentRun.event_id == event_id).with_for_update())


def _ensure_identity(
    run: AgentRun,
    *,
    agent_run_id: str,
    trace_id: str,
    tenant_id: str,
    student_id: str,
) -> None:
    expected = (
        agent_run_id,
        trace_id,
        _uuid(tenant_id, "tenant_id"),
        _uuid(student_id, "student_id"),
    )
    actual = (run.external_run_id, run.trace_id, run.tenant_id, run.student_id)
    if actual != expected:
        raise ValueError("agent event identity does not match the persisted run")


def _definition(db: Session, node: str | None) -> AgentDefinition | None:
    if node is None:
        return None
    definition = db.scalar(
        select(AgentDefinition).where(
            AgentDefinition.name == node,
            AgentDefinition.version == 1,
        )
    )
    if definition is None:
        definition = AgentDefinition(
            name=node,
            version=1,
            allowed_tools=[],
            policy_snapshot={"node": node, "policy_version": 1},
        )
        db.add(definition)
        db.flush()
    return definition


def _may_transition(current: str, requested: str) -> bool:
    if current in _TERMINAL_STATUSES:
        return current == requested
    return True


def ingest_agent_audit(db: Session, event: AgentAuditEnvelope) -> AgentRun:
    """Apply one safe audit envelope, tolerating duplicates and out-of-order delivery."""

    detail = _safe_detail(event)
    node = event.node.value if event.node is not None else None
    event_type = event.event_type.value
    run = _load_run(db, event.event_id)
    if run is None:
        run = AgentRun(
            external_run_id=event.agent_run_id,
            event_id=event.event_id,
            trace_id=event.trace_id,
            tenant_id=_uuid(event.tenant_id, "tenant_id"),
            student_id=_uuid(event.student_id, "student_id"),
            status="QUEUED",
            checkpoint_thread_id=event.agent_run_id,
            safe_input_snapshot={},
            safe_output_snapshot={},
        )
        db.add(run)
        db.flush()
    else:
        _ensure_identity(
            run,
            agent_run_id=event.agent_run_id,
            trace_id=event.trace_id,
            tenant_id=event.tenant_id,
            student_id=event.student_id,
        )

    definition = _definition(db, node)
    if definition is not None and run.definition_id is None:
        run.definition_id = definition.id

    if event_type in _TOOL_EVENTS and event.tool_name is not None:
        existing = db.scalar(
            select(AgentToolCall).where(
                AgentToolCall.agent_run_id == run.id,
                AgentToolCall.sequence == event.sequence,
            )
        )
        if existing is None:
            db.add(
                AgentToolCall(
                    tenant_id=run.tenant_id,
                    agent_run_id=run.id,
                    sequence=event.sequence,
                    node=node,
                    tool_name=event.tool_name,
                    event_type=event_type,
                    status=detail.get("status"),
                    argument_digest=detail.get("argument_digest"),
                    result_digest=detail.get("result_digest"),
                    latency_ms=detail.get("latency_ms", 0),
                    retry_count=detail.get("retry_count", 0),
                    error_code=detail.get("code"),
                    occurred_at=event.occurred_at,
                )
            )

    if event.sequence > run.latest_sequence:
        requested_status = detail.get("status")
        if isinstance(requested_status, str) and _may_transition(run.status, requested_status):
            run.status = requested_status
        run.latest_sequence = event.sequence
        if node is not None and node != "orchestrator":
            run.route = node
        if event.checkpoint_id is not None:
            run.checkpoint_thread_id = event.agent_run_id
            run.latest_checkpoint_id = event.checkpoint_id
        if "fallback" in detail:
            run.fallback_used = bool(detail["fallback"])
        error_code = detail.get("code")
        if isinstance(error_code, str):
            run.error_code = error_code
        if event_type == "RUN_STARTED":
            run.started_at = event.occurred_at
        if event_type in {"RUN_COMPLETED", "RUN_FAILED", "RUN_CANCELLED"}:
            run.completed_at = event.occurred_at
        if event_type in _INPUT_EVENTS:
            run.safe_input_snapshot = detail
        elif event_type not in _TOOL_EVENTS:
            run.safe_output_snapshot = detail

    db.flush()
    return run


def ingest_agent_proposal(db: Session, envelope: AgentProposalEnvelope) -> AgentRun:
    """Attach a terminal worker proposal to its existing run without replacing it."""

    run = _load_run(db, envelope.event_id)
    if run is None:
        run = AgentRun(
            external_run_id=envelope.agent_run_id,
            event_id=envelope.event_id,
            trace_id=envelope.trace_id,
            tenant_id=_uuid(envelope.tenant_id, "tenant_id"),
            student_id=_uuid(envelope.student_id, "student_id"),
            status="QUEUED",
            checkpoint_thread_id=envelope.agent_run_id,
            safe_input_snapshot={},
            safe_output_snapshot={},
        )
        db.add(run)
        db.flush()
    else:
        _ensure_identity(
            run,
            agent_run_id=envelope.agent_run_id,
            trace_id=envelope.trace_id,
            tenant_id=envelope.tenant_id,
            student_id=envelope.student_id,
        )

    node = envelope.node.value
    definition = _definition(db, node)
    run.definition_id = definition.id if definition is not None else None
    run.route = node
    if _may_transition(run.status, envelope.status):
        run.status = envelope.status
        run.fallback_used = envelope.fallback_used
        run.error_code = envelope.error_code
        run.completed_at = envelope.completed_at
        run.safe_output_snapshot = (
            envelope.proposal.model_dump(mode="json", exclude_none=True)
            if envelope.proposal is not None
            else {}
        )
    db.flush()
    return run


def get_agent_replay_metadata(db: Session, event_id: str) -> AgentReplayMetadata:
    run = db.scalar(select(AgentRun).where(AgentRun.event_id == event_id))
    if run is None or run.checkpoint_thread_id is None or run.latest_checkpoint_id is None:
        raise LookupError("agent run has no replayable checkpoint")
    return AgentReplayMetadata(
        agent_run_id=run.external_run_id,
        event_id=run.event_id,
        thread_id=run.checkpoint_thread_id,
        checkpoint_id=run.latest_checkpoint_id,
    )
