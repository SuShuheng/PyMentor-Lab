"""Redis agent-event ingestion is transactional, recoverable, and opt-in."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent_event_consumer import consume_agent_events_once, run_agent_event_consumer
from app.config import Settings
from app.models import AgentRun, Tenant, User, UserStatus

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


class FakeRedis:
    def __init__(
        self,
        *,
        fresh: list[tuple[str, dict[str, str]]] | None = None,
        pending: list[tuple[str, dict[str, str]]] | None = None,
    ) -> None:
        self.fresh = fresh or []
        self.pending = pending or []
        self.acked: list[str] = []
        self.groups: list[tuple[str, str]] = []
        self.closed = False

    async def xgroup_create(self, stream: str, group: str, *, id: str, mkstream: bool) -> bool:
        del id, mkstream
        self.groups.append((stream, group))
        return True

    async def xautoclaim(self, *args: object, **kwargs: object) -> list[object]:
        del args, kwargs
        claimed, self.pending = self.pending, []
        return ["0-0", claimed, []]

    async def xreadgroup(self, *args: object, **kwargs: object) -> list[object]:
        del args, kwargs
        fresh, self.fresh = self.fresh, []
        return [["pymentor:agent-events:v1", fresh]] if fresh else []

    async def xack(self, stream: str, group: str, message_id: str) -> int:
        del stream, group
        self.acked.append(message_id)
        return 1

    async def aclose(self) -> None:
        self.closed = True


def settings(**overrides: object) -> Settings:
    return Settings(
        agent_event_consumer_enabled=True,
        agent_event_stream="pymentor:agent-events:v1",
        agent_event_group="pymentor-api-v1",
        agent_event_consumer="test-api",
        agent_event_block_ms=1,
        agent_event_batch_size=10,
        agent_event_claim_idle_ms=1,
        **overrides,
    )


def payload(*, tenant_id: str, student_id: str, event_id: str, run_id: str) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "agent_run_id": run_id,
            "event_id": event_id,
            "trace_id": f"trace-{event_id}",
            "tenant_id": tenant_id,
            "student_id": student_id,
            "sequence": 1,
            "event_type": "RUN_STARTED",
            "detail": {"status": "RUNNING", "retry_count": 0},
            "occurred_at": NOW.isoformat(),
        }
    )


@pytest.fixture()
def agent_identity(db_session: Session) -> tuple[Tenant, User, str, str]:
    suffix = uuid4().hex
    tenant = Tenant(slug=f"consumer-{suffix}", name="Agent Consumer")
    db_session.add(tenant)
    db_session.flush()
    student = User(
        tenant_id=tenant.id,
        email=f"consumer-{suffix}@example.com",
        password_hash="not-used",
        status=UserStatus.ACTIVE,
    )
    db_session.add(student)
    db_session.flush()
    return tenant, student, f"event-{suffix}", f"run-{suffix}"


@pytest.fixture()
def session_factory(db_session: Session) -> Callable[[], Session]:
    connection = db_session.connection()

    def factory() -> Session:
        return Session(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

    return factory


@pytest.mark.asyncio
async def test_valid_event_commits_before_ack_and_duplicate_delivery_is_idempotent(
    db_session: Session,
    session_factory: Callable[[], Session],
    agent_identity: tuple[Tenant, User, str, str],
) -> None:
    tenant, student, event_id, run_id = agent_identity
    body = payload(
        tenant_id=str(tenant.id),
        student_id=str(student.id),
        event_id=event_id,
        run_id=run_id,
    )
    redis = FakeRedis(
        fresh=[
            ("1-0", {"payload": body}),
            ("2-0", {"payload": body}),
        ]
    )

    consumed = await consume_agent_events_once(redis, session_factory, settings())

    assert consumed == 2
    assert redis.acked == ["1-0", "2-0"]
    db_session.expire_all()
    assert (
        db_session.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.event_id == event_id)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_invalid_event_rolls_back_and_is_not_acknowledged(
    db_session: Session,
    session_factory: Callable[[], Session],
) -> None:
    redis = FakeRedis(fresh=[("1-0", {"payload": '{"raw_prompt":"secret"}'})])
    count_before = db_session.scalar(select(func.count()).select_from(AgentRun))

    consumed = await consume_agent_events_once(redis, session_factory, settings())

    assert consumed == 0
    assert redis.acked == []
    assert db_session.scalar(select(func.count()).select_from(AgentRun)) == count_before


@pytest.mark.asyncio
async def test_pending_message_is_claimed_and_ingested_before_fresh_reads(
    db_session: Session,
    session_factory: Callable[[], Session],
    agent_identity: tuple[Tenant, User, str, str],
) -> None:
    tenant, student, event_id, run_id = agent_identity
    redis = FakeRedis(
        pending=[
            (
                "1-0",
                {
                    "payload": payload(
                        tenant_id=str(tenant.id),
                        student_id=str(student.id),
                        event_id=event_id,
                        run_id=run_id,
                    )
                },
            )
        ]
    )

    consumed = await consume_agent_events_once(redis, session_factory, settings())

    assert consumed == 1
    assert redis.acked == ["1-0"]
    db_session.expire_all()
    assert (
        db_session.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.event_id == event_id)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_run_loop_closes_redis_and_preserves_cancellation(
    session_factory: Callable[[], Session],
) -> None:
    redis = FakeRedis()
    task = asyncio.create_task(run_agent_event_consumer(redis, session_factory, settings()))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert redis.closed is True


def test_consumer_is_disabled_by_default() -> None:
    assert Settings().agent_event_consumer_enabled is False
