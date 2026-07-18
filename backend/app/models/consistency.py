"""一致性与可观测性 ORM 模型（设计 §15.1 第 8 组「Agent 与一致性」+ 证据表组）。

表：evidence_events, audit_events, outbox_events, idempotency_keys。
设计依据：
- §6.1：append-only 证据/审计；状态变更与 Outbox 同事务；Worker 按 event_id 幂等消费。
- §15.3：证据 event_id 唯一；Outbox 与状态变更同事务。
- §20.2：API 命令支持 Idempotency-Key；Outbox 消费按 event_id 去重。
字段规范遵循 §12.2：UUID 主键、created_at/updated_at、JSONB 不替代关系模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import Uuid

from app.db import Base


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid4)


class EvidenceEvent(Base):
    """append-only 学习证据。event_id 唯一（设计 §15.3 证据去重）。

    覆盖交互、尝试、提示、代码运行、测试、轨迹预测、测评等（设计 §6.2 核心事件）。
    """

    __tablename__ = "evidence_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_evidence_event_id"),
        CheckConstraint(
            "evidence_confidence >= 0.0 AND evidence_confidence <= 1.0",
            name="ck_evidence_confidence_range",
        ),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    course_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    node_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    agent_run_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_confidence: Mapped[float] = mapped_column(default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class AuditEvent(Base):
    """append-only 审计事件。管理操作、状态变更、安全事件。

    所有管理操作写审计（设计 §17.2）。BE-002 的 admin 路由通过 trace_id 关联，
    本表提供正式审计持久化。
    """

    __tablename__ = "audit_events"

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class OutboxEvent(Base):
    """事务性 Outbox 事件（设计 §6.1：状态变更与 Outbox 同事务提交）。

    event_id 唯一：Worker 按 event_id 幂等消费（设计 §20.2）。
    published=false 的行由消费者 claim + mark_published 处理。
    """

    __tablename__ = "outbox_events"
    __table_args__ = (UniqueConstraint("event_id", name="uq_outbox_event_id"),)

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    published: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class IdempotencyKey(Base):
    """API 命令幂等记录（设计 §20.2：API 命令支持 Idempotency-Key）。

    key 唯一：相同 key 的重复请求返回缓存的 response_status + response_body。
    expires_at 支持过期清理。
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("key", name="uq_idempotency_keys_key"),)

    id: Mapped[UUID] = _uuid_pk()
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    response_status: Mapped[int | None] = mapped_column(nullable=True)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
