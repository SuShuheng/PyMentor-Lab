"""Unit of Work：封装「正式状态变更 + Outbox 事件在同一事务提交」的原子性。

设计 §6.1：状态变更与 Outbox 事件在同一事务提交。
调用方在 UoW 内修改正式状态并调用 publish()，commit 时两者原子提交；
失败时两者一起回滚，永不出现「状态变了但事件丢了」或反之。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.db import SessionLocal
from app.models.consistency import OutboxEvent


class SqlAlchemyUnitOfWork:
    """事务工作单元。

    用法::

        with SqlAlchemyUnitOfWork() as uow:
            user = uow.session.get(User, uid)
            user.status = UserStatus.ACTIVE
            uow.publish(
                event_type="USER_ACTIVATED",
                aggregate_type="user",
                aggregate_id=str(uid),
                tenant_id=tenant_id,
                trace_id=trace_id,
                payload={"user_id": str(uid)},
            )
            uow.commit()  # 状态 + Outbox 原子提交
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        *,
        accept_session: Session | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._accepted_session = accept_session
        self._owns_session = accept_session is None
        self.session: Session | None = None

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        self.session = (
            self._accepted_session
            if self._accepted_session is not None
            else self._session_factory()
        )
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if self.session is not None:
            if exc_type is not None:
                self.rollback()
            if self._owns_session:
                self.session.close()
            self.session = None

    def commit(self) -> None:
        """提交事务：正式状态变更 + Outbox 事件一起持久化。"""
        assert self.session is not None, "UoW used outside context manager"
        self.session.commit()

    def rollback(self) -> None:
        """回滚事务：正式状态变更 + Outbox 事件一起撤销。"""
        assert self.session is not None, "UoW used outside context manager"
        self.session.rollback()

    def publish(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        tenant_id: UUID,
        trace_id: str,
        payload: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> OutboxEvent:
        """向 Outbox 添加事件行（与状态变更同事务）。

        event_id 默认生成唯一值；调用方可传入自定义 event_id（幂等消费键）。
        """
        assert self.session is not None, "UoW used outside context manager"
        event = OutboxEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            event_id=event_id or f"evt_{uuid4().hex}",
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            trace_id=trace_id,
            payload=payload or {},
        )
        self.session.add(event)
        self.session.flush()
        return event


def uow_factory() -> Iterator[SqlAlchemyUnitOfWork]:
    """FastAPI 依赖：每请求一个 UoW。"""
    with SqlAlchemyUnitOfWork() as uow:
        yield uow


def utc_now() -> datetime:
    return datetime.now(UTC)
