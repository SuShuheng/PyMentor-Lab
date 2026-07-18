"""证据服务：append-only 学习证据的写入与查询。

设计 §15.3：证据 event_id 唯一（去重）。
设计 §6.1：学习证据 append-only。
设计：证据可按学生、课程、节点、时间查询。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.consistency import EvidenceEvent


def record_evidence(
    db: Session,
    *,
    tenant_id: UUID,
    student_id: UUID,
    event_id: str,
    event_type: str,
    trace_id: str,
    payload: dict[str, Any] | None = None,
    course_id: UUID | None = None,
    node_id: UUID | None = None,
    task_id: UUID | None = None,
    agent_run_id: UUID | None = None,
    evidence_confidence: float = 1.0,
) -> EvidenceEvent | None:
    """写入一条证据。event_id 重复时返回 None（幂等去重）。

    唯一约束 uq_evidence_event_id 兜底并发写入。调用方负责 commit。
    """
    event = EvidenceEvent(
        tenant_id=tenant_id,
        student_id=student_id,
        event_id=event_id,
        event_type=event_type,
        trace_id=trace_id,
        payload=payload or {},
        course_id=course_id,
        node_id=node_id,
        task_id=task_id,
        agent_run_id=agent_run_id,
        evidence_confidence=evidence_confidence,
    )
    try:
        # 仅让本次插入进入 savepoint。并发/重复 event_id 冲突不能回滚调用方
        # 同一正式事务中已经写入的状态、证据或 Outbox。
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError as exc:
        diag = getattr(exc.orig, "diag", None)
        if getattr(diag, "constraint_name", None) == "uq_evidence_event_id":
            return None
        raise
    return event


def list_evidence(
    db: Session,
    *,
    tenant_id: UUID,
    student_id: UUID | None = None,
    course_id: UUID | None = None,
    node_id: UUID | None = None,
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[EvidenceEvent]:
    """按维度查询证据（租户隔离必填，其余可选过滤）。"""
    stmt = select(EvidenceEvent).where(EvidenceEvent.tenant_id == tenant_id)
    if student_id is not None:
        stmt = stmt.where(EvidenceEvent.student_id == student_id)
    if course_id is not None:
        stmt = stmt.where(EvidenceEvent.course_id == course_id)
    if node_id is not None:
        stmt = stmt.where(EvidenceEvent.node_id == node_id)
    if event_type is not None:
        stmt = stmt.where(EvidenceEvent.event_type == event_type)
    stmt = stmt.order_by(EvidenceEvent.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def record_audit(
    db: Session,
    *,
    tenant_id: UUID,
    action: str,
    resource_type: str,
    resource_id: str,
    trace_id: str,
    actor_user_id: UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """写入一条审计事件（管理操作/状态变更）。调用方负责 commit。"""
    from app.models.consistency import AuditEvent

    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            trace_id=trace_id,
            detail=detail or {},
        )
    )
    db.flush()
