"""幂等性服务：API 命令的 Idempotency-Key 处理。

设计 §20.2：API 命令支持 Idempotency-Key。
相同 key 的重复请求返回缓存的 response_status + response_body。
过期 key 被忽略（视为新请求）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.consistency import IdempotencyKey

IDEMPOTENCY_TTL_HOURS = 24


class IdempotencyScopeConflictError(ValueError):
    """同一幂等键被用于不同租户、端点或用户作用域。"""


def get_or_create_idempotency(
    db: Session,
    *,
    key: str,
    tenant_id: UUID,
    endpoint: str,
    user_id: UUID | None = None,
) -> IdempotencyKey | None:
    """查询已有幂等记录或创建新记录。

    返回值：
    - 已有且未过期 → 返回该记录；response_status=None 表示仍在处理中。
    - 已有但已过期 → 返回 None（视为新请求，调用方重新处理）。
    - 不存在 → 创建新记录（response_status=None），返回 None（调用方处理后调 save_response）。
    - 同一 key 的租户、端点或用户不一致 → 抛 IdempotencyScopeConflictError。
    调用方负责 commit。
    """
    now = datetime.now(UTC)
    existing = db.scalar(select(IdempotencyKey).where(IdempotencyKey.key == key))
    if existing is not None:
        if (
            existing.tenant_id != tenant_id
            or existing.endpoint != endpoint
            or existing.user_id != user_id
        ):
            raise IdempotencyScopeConflictError(
                "idempotency key scope conflict"
            )
        if existing.expires_at > now:
            return existing
        # 仅过期记录允许删除并重新处理；未完成记录继续占位。
        db.delete(existing)
        db.flush()

    record = IdempotencyKey(
        key=key,
        tenant_id=tenant_id,
        user_id=user_id,
        endpoint=endpoint,
        expires_at=now + timedelta(hours=IDEMPOTENCY_TTL_HOURS),
    )
    db.add(record)
    db.flush()
    return None


def save_response(
    db: Session,
    *,
    key: str,
    response_status: int,
    response_body: dict[str, Any] | None = None,
) -> None:
    """缓存命令的响应到幂等记录。调用方负责 commit。"""
    db.execute(
        update(IdempotencyKey)
        .where(
            IdempotencyKey.key == key,
            IdempotencyKey.response_status.is_(None),
        )
        .values(response_status=response_status, response_body=response_body)
    )
    db.flush()


def extract_idempotency_key(request: Request) -> str | None:
    """从请求头提取 Idempotency-Key。"""
    return request.headers.get("Idempotency-Key")
