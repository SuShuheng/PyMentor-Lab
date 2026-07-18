"""Transactional Redis Stream consumer for redacted Worker audit events."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.orm import Session

from app.agent_audit import ingest_agent_audit, ingest_agent_proposal
from app.config import Settings
from app.contracts.worker import AgentAuditEnvelope, AgentProposalEnvelope

logger = logging.getLogger(__name__)


class AgentEventRedisPort(Protocol):
    async def xgroup_create(
        self, stream: str, group: str, *, id: str, mkstream: bool
    ) -> object: ...

    async def xautoclaim(self, *args: object, **kwargs: object) -> object: ...

    async def xreadgroup(self, *args: object, **kwargs: object) -> object: ...

    async def xack(self, stream: str, group: str, message_id: str) -> object: ...

    async def xadd(
        self,
        stream: str,
        fields: Mapping[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> object: ...

    async def aclose(self) -> None: ...


SessionFactory = Callable[[], Session]
StreamFields = Mapping[str | bytes, str | bytes]
StreamMessage = tuple[str, StreamFields]


@dataclass(slots=True)
class AgentEventConsumerState:
    claim_cursor: str = "0-0"


@dataclass(slots=True)
class AgentEventConsumerHealth:
    alive: bool = False
    ready: bool = False
    failure_count: int = 0
    last_error: str | None = None


def create_agent_event_redis(settings: Settings) -> AgentEventRedisPort:
    return cast(
        AgentEventRedisPort,
        Redis.from_url(settings.redis_url, decode_responses=True),
    )


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise ValueError("Redis stream value must be text")


def _messages(value: object) -> list[StreamMessage]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    messages: list[StreamMessage] = []
    for item in value:
        if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) != 2:
            continue
        message_id, fields = item
        if not isinstance(fields, Mapping):
            continue
        messages.append((_text(message_id), fields))
    return messages


def _claimed_batch(value: object) -> tuple[str, list[StreamMessage]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 2:
        return "0-0", []
    return _text(value[0]), _messages(value[1])


def _fresh_messages(value: object) -> list[StreamMessage]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    messages: list[StreamMessage] = []
    for stream_result in value:
        if (
            not isinstance(stream_result, Sequence)
            or isinstance(stream_result, (str, bytes))
            or len(stream_result) != 2
        ):
            continue
        messages.extend(_messages(stream_result[1]))
    return messages


def _payload(fields: StreamFields) -> str:
    value = fields.get("payload", fields.get(b"payload"))
    return _text(value)


def _ingest(db: Session, raw_payload: str) -> None:
    decoded = json.loads(raw_payload)
    if not isinstance(decoded, dict):
        raise ValueError("agent event payload must be an object")
    if "event_type" in decoded:
        ingest_agent_audit(db, AgentAuditEnvelope.model_validate(decoded))
        return
    ingest_agent_proposal(db, AgentProposalEnvelope.model_validate(decoded))


async def _ensure_group(redis: AgentEventRedisPort, settings: Settings) -> None:
    try:
        await redis.xgroup_create(
            settings.agent_event_stream,
            settings.agent_event_group,
            id="0",
            mkstream=True,
        )
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def _process_messages(
    redis: AgentEventRedisPort,
    session_factory: SessionFactory,
    settings: Settings,
    messages: Sequence[StreamMessage],
) -> int:
    acknowledged = 0
    for message_id, fields in messages:
        try:
            raw_payload = _payload(fields)
            with session_factory() as db, db.begin():
                _ingest(db, raw_payload)
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError):
            logger.warning("Agent event %s failed validation; isolating to DLQ", message_id)
            try:
                await redis.xadd(
                    settings.agent_event_dlq,
                    {
                        "payload": json.dumps(
                            {
                                "schema_version": 1,
                                "source_stream": settings.agent_event_stream,
                                "message_id": message_id,
                                "code": "VALIDATION_ERROR",
                                "occurred_at": datetime.now(UTC).isoformat(),
                            },
                            separators=(",", ":"),
                        )
                    },
                    maxlen=settings.agent_event_dlq_maxlen,
                    approximate=True,
                )
                await redis.xack(
                    settings.agent_event_stream,
                    settings.agent_event_group,
                    message_id,
                )
                acknowledged += 1
            except Exception:
                logger.exception(
                    "Agent event %s could not be isolated; leaving pending", message_id
                )
            continue
        except Exception:
            logger.exception("Agent event %s failed persistence; leaving pending", message_id)
            continue
        await redis.xack(
            settings.agent_event_stream,
            settings.agent_event_group,
            message_id,
        )
        acknowledged += 1
    return acknowledged


async def consume_agent_events_once(
    redis: AgentEventRedisPort,
    session_factory: SessionFactory,
    settings: Settings,
    state: AgentEventConsumerState | None = None,
) -> int:
    """Recover pending events, read a bounded fresh batch, and ACK commits only."""

    await _ensure_group(redis, settings)
    consumer_state = state or AgentEventConsumerState()
    claimed = await redis.xautoclaim(
        settings.agent_event_stream,
        settings.agent_event_group,
        settings.agent_event_consumer,
        settings.agent_event_claim_idle_ms,
        consumer_state.claim_cursor,
        count=settings.agent_event_batch_size,
    )
    next_cursor, pending_messages = _claimed_batch(claimed)
    consumer_state.claim_cursor = next_cursor
    acknowledged = await _process_messages(redis, session_factory, settings, pending_messages)

    fresh = await redis.xreadgroup(
        settings.agent_event_group,
        settings.agent_event_consumer,
        {settings.agent_event_stream: ">"},
        count=settings.agent_event_batch_size,
        block=settings.agent_event_block_ms,
    )
    return acknowledged + await _process_messages(
        redis,
        session_factory,
        settings,
        _fresh_messages(fresh),
    )


async def run_agent_event_consumer(
    redis: AgentEventRedisPort,
    session_factory: SessionFactory,
    settings: Settings,
    health: AgentEventConsumerHealth | None = None,
) -> None:
    """Run until cancelled, retry transient failures, and expose readiness."""

    consumer_health = health or AgentEventConsumerHealth()
    state = AgentEventConsumerState()
    retry_delay_ms = settings.agent_event_retry_base_ms
    consumer_health.alive = True
    try:
        while True:
            try:
                await consume_agent_events_once(redis, session_factory, settings, state)
                consumer_health.ready = True
                consumer_health.failure_count = 0
                consumer_health.last_error = None
                retry_delay_ms = settings.agent_event_retry_base_ms
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                consumer_health.ready = False
                consumer_health.failure_count += 1
                consumer_health.last_error = type(exc).__name__
                logger.exception("Agent event consumer failed; retrying with backoff")
                await asyncio.sleep(retry_delay_ms / 1000)
                retry_delay_ms = min(settings.agent_event_retry_max_ms, retry_delay_ms * 2)
    finally:
        consumer_health.ready = False
        consumer_health.alive = False
        await redis.aclose()
