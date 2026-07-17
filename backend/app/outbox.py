"""Outbox 消费者：claim 未发布事件 + 标记已发布 + 幂等重放安全。

设计 §6.1：Worker 按 event_id 幂等消费。
设计 §20.2：Outbox 消费按 event_id 去重。
行锁：FOR UPDATE SKIP LOCKED 防止并发消费者重复获取（设计 §6.1：行锁）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.consistency import OutboxEvent


def claim_unpublished(db: Session, *, batch_size: int = 50) -> list[OutboxEvent]:
    """获取一批未发布的 Outbox 事件（行锁，并发安全）。

    使用 FOR UPDATE SKIP LOCKED：并发消费者不会获取同一行。
    调用方负责在处理完成后调用 mark_published 并 commit。
    """
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.published == False)  # noqa: E712
        .order_by(OutboxEvent.created_at.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    return list(db.scalars(stmt))


def mark_published(db: Session, event: OutboxEvent) -> None:
    """标记事件已发布。调用方负责 commit。"""
    event.published = True
    event.published_at = datetime.now(UTC)
    db.flush()


def is_event_consumed(db: Session, event_id: str) -> bool:
    """检查某 event_id 是否已被消费（published=True）。

    幂等重放保护：消费者在处理前检查此函数，避免重复效果。
    """
    event = db.scalar(select(OutboxEvent).where(OutboxEvent.event_id == event_id))
    return event is not None and event.published
