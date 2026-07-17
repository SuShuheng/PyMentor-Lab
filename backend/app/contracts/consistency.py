"""一致性基础设施契约（Pydantic 镜像）。

Mirror of ``packages/contracts/src/consistency.ts``。
设计依据：§6.1 append-only 证据、§20.2 幂等、§15.3 必须约束。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceEventType(StrEnum):
    """证据事件类型（设计 §6.2 核心事件子集，BE-003 建立基础类型）。"""

    INTERACTION_ACCEPTED = "INTERACTION_ACCEPTED"
    EVIDENCE_RECORDED = "EVIDENCE_RECORDED"
    CODE_RUN_COMPLETED = "CODE_RUN_COMPLETED"
    CODE_RUN_FAILED = "CODE_RUN_FAILED"
    ASSESSMENT_RECORDED = "ASSESSMENT_RECORDED"
    MASTERY_DECIDED = "MASTERY_DECIDED"
    REVIEW_COMPLETED = "REVIEW_COMPLETED"


class EvidenceEvent(BaseModel):
    """学习证据记录（append-only，event_id 唯一）。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    student_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: str = Field(min_length=1)
    course_id: str | None = None
    node_id: str | None = None
    task_id: str | None = None


class AuditEvent(BaseModel):
    """审计事件（append-only）。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    detail: dict[str, Any] = Field(default_factory=dict)
    actor_user_id: str | None = None
    created_at: str = Field(min_length=1)


class OutboxEventModel(BaseModel):
    """Outbox 事件（事务性，event_id 唯一幂等消费）。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    aggregate_type: str = Field(min_length=1)
    aggregate_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    published: bool = False
    created_at: str = Field(min_length=1)


class IdempotencyRecord(BaseModel):
    """幂等性记录。"""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    response_status: int | None = None
    response_body: dict[str, Any] | None = None
