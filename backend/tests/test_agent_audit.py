"""Agent audit persistence stays idempotent, normalized, and redacted."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent_audit import (
    get_agent_replay_metadata,
    ingest_agent_audit,
    ingest_agent_proposal,
)
from app.contracts.worker import AgentAuditEnvelope, AgentProposalEnvelope
from app.models import AgentToolCall, Tenant, User, UserStatus

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


@dataclass(slots=True)
class AgentContext:
    tenant: Tenant
    student: User
    event_id: str
    run_id: str


@pytest.fixture()
def agent_context(db_session: Session) -> AgentContext:
    suffix = uuid4().hex
    tenant = Tenant(slug=f"agent-{suffix}", name="Agent Audit")
    db_session.add(tenant)
    db_session.flush()
    student = User(
        tenant_id=tenant.id,
        email=f"agent-{suffix}@example.com",
        password_hash="not-used",
        status=UserStatus.ACTIVE,
    )
    db_session.add(student)
    db_session.flush()
    return AgentContext(
        tenant=tenant,
        student=student,
        event_id=f"event-{suffix}",
        run_id=f"run-{suffix}",
    )


def audit(
    context: AgentContext,
    *,
    sequence: int,
    event_type: str,
    detail: dict[str, object],
    **extra: object,
) -> AgentAuditEnvelope:
    return AgentAuditEnvelope.model_validate(
        {
            "schema_version": 1,
            "agent_run_id": context.run_id,
            "event_id": context.event_id,
            "trace_id": f"trace-{context.event_id}",
            "tenant_id": str(context.tenant.id),
            "student_id": str(context.student.id),
            "sequence": sequence,
            "event_type": event_type,
            "detail": detail,
            "occurred_at": NOW,
            **extra,
        }
    )


def proposal(
    context: AgentContext,
    *,
    status: str = "SUCCEEDED",
) -> AgentProposalEnvelope:
    payload: dict[str, object] = {
        "schema_version": 1,
        "agent_run_id": context.run_id,
        "event_id": context.event_id,
        "trace_id": f"trace-{context.event_id}",
        "tenant_id": str(context.tenant.id),
        "student_id": str(context.student.id),
        "node": "coach",
        "status": status,
        "proposal": {
            "kind": "coaching_feedback",
            "diagnosis": "The loop bound excludes the final index.",
            "hints": ["Compare the final index with the condition."],
            "next_test": "Test lengths zero and one.",
        }
        if status == "SUCCEEDED"
        else None,
        "fallback_used": False,
        "completed_at": NOW,
    }
    if status != "SUCCEEDED":
        payload["error_code"] = "PROVIDER_UNAVAILABLE"
    return AgentProposalEnvelope.model_validate(payload)


def test_duplicate_audit_is_idempotent_and_tool_rows_are_unique(
    db_session: Session,
    agent_context: AgentContext,
) -> None:
    event = audit(
        agent_context,
        sequence=2,
        event_type="TOOL_COMPLETED",
        detail={
            "status": "SUCCEEDED",
            "argument_digest": "a" * 64,
            "result_digest": "b" * 64,
            "latency_ms": 12,
            "retry_count": 0,
        },
        node="coach",
        tool_name="knowledge.search",
    )

    first = ingest_agent_audit(db_session, event)
    second = ingest_agent_audit(db_session, event)
    db_session.flush()

    assert second.id == first.id
    count = db_session.scalar(select(func.count()).select_from(AgentToolCall))
    assert count == 1
    tool = db_session.scalar(select(AgentToolCall))
    assert tool is not None
    assert tool.argument_digest == "a" * 64
    assert tool.result_digest == "b" * 64


def test_terminal_proposal_updates_the_existing_run_without_replacing_it(
    db_session: Session,
    agent_context: AgentContext,
) -> None:
    started = audit(
        agent_context,
        sequence=1,
        event_type="RUN_STARTED",
        detail={"status": "RUNNING", "retry_count": 0},
    )
    run = ingest_agent_audit(db_session, started)
    original_id = run.id

    updated = ingest_agent_proposal(db_session, proposal(agent_context))
    db_session.flush()

    assert updated.id == original_id
    assert updated.status == "SUCCEEDED"
    assert updated.route == "coach"
    assert updated.safe_output_snapshot == {
        "kind": "coaching_feedback",
        "diagnosis": "The loop bound excludes the final index.",
        "hints": ["Compare the final index with the condition."],
        "next_test": "Test lengths zero and one.",
    }


def test_out_of_order_audit_cannot_regress_a_terminal_status(
    db_session: Session,
    agent_context: AgentContext,
) -> None:
    completed = audit(
        agent_context,
        sequence=5,
        event_type="RUN_COMPLETED",
        detail={"status": "SUCCEEDED", "fallback": False},
    )
    stale_started = audit(
        agent_context,
        sequence=2,
        event_type="RUN_STARTED",
        detail={"status": "RUNNING"},
    )

    ingest_agent_audit(db_session, completed)
    run = ingest_agent_audit(db_session, stale_started)
    db_session.flush()

    assert run.status == "SUCCEEDED"
    assert run.latest_sequence == 5


def test_checkpoint_metadata_is_available_for_replay(
    db_session: Session,
    agent_context: AgentContext,
) -> None:
    checkpoint = audit(
        agent_context,
        sequence=3,
        event_type="CHECKPOINT_SAVED",
        detail={"status": "RUNNING"},
        checkpoint_id="checkpoint-1",
    )
    ingest_agent_audit(db_session, checkpoint)
    db_session.flush()

    metadata = get_agent_replay_metadata(db_session, agent_context.event_id)
    assert metadata.agent_run_id == agent_context.run_id
    assert metadata.thread_id == agent_context.run_id
    assert metadata.checkpoint_id == "checkpoint-1"


def test_contract_and_persistence_allow_only_redacted_detail_keys(
    db_session: Session,
    agent_context: AgentContext,
) -> None:
    with pytest.raises(ValidationError):
        audit(
            agent_context,
            sequence=1,
            event_type="RUN_STARTED",
            detail={"status": "RUNNING", "raw_prompt": "do not persist"},
        )

    event = audit(
        agent_context,
        sequence=1,
        event_type="RUN_STARTED",
        detail={"status": "RUNNING", "input_bytes": 42, "argument_digest": "c" * 64},
    )
    run = ingest_agent_audit(db_session, event)
    db_session.flush()
    assert set(run.safe_input_snapshot) == {
        "status",
        "input_bytes",
        "argument_digest",
    }
