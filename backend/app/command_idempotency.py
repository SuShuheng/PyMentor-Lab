"""API command adapter for scoped idempotency reservations (BE-004)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.idempotency import extract_idempotency_key, get_or_create_idempotency
from app.models import IdempotencyKey


class IdempotencyInProgressError(Exception):
    """A matching reservation exists but its first response is not committed."""


@dataclass(frozen=True)
class CommandScope:
    tenant_id: UUID
    user_id: UUID
    endpoint: str
    key: str


def require_idempotency_key(request: Request) -> str:
    key = extract_idempotency_key(request)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="valid Idempotency-Key required",
        )
    clean_key = key.strip()
    if not 1 <= len(clean_key) <= 128:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="valid Idempotency-Key required",
        )
    return clean_key


def scope_for_request(request: Request, *, tenant_id: UUID, user_id: UUID) -> CommandScope:
    return CommandScope(
        tenant_id=tenant_id,
        user_id=user_id,
        endpoint=f"{request.method.upper()} {request.url.path}",
        key=require_idempotency_key(request),
    )


def begin_command(db: Session, scope: CommandScope) -> IdempotencyKey | None:
    existing = get_or_create_idempotency(
        db,
        key=scope.key,
        tenant_id=scope.tenant_id,
        user_id=scope.user_id,
        endpoint=scope.endpoint,
    )
    if existing is not None and existing.response_status is None:
        raise IdempotencyInProgressError("idempotent command is still in progress")
    return existing
