"""Authenticated, ordered SSE relay for BE-007 tutoring streams."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.streaming import (
    ChatCompletionRequest,
    DoneEvent,
    StreamErrorEvent,
    StreamEvent,
    StreamInlineError,
)
from app.db import get_db
from app.models import CourseCatalog, KnowledgeNode, User
from app.rbac import get_current_user

router = APIRouter(prefix="/api/v1/chat", tags=["tutoring-stream"])
_stream_adapter: TypeAdapter[StreamEvent] = TypeAdapter(StreamEvent)


class ChatStreamFailure(Exception):
    def __init__(self, code: str, retryable: bool, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ChatStreamService(Protocol):
    def stream(
        self,
        *,
        body: ChatCompletionRequest,
        user: User,
        after_event_id: str | None,
    ) -> AsyncIterator[StreamEvent]: ...


class _UnavailableChatStreamService:
    async def stream(
        self,
        *,
        body: ChatCompletionRequest,
        user: User,
        after_event_id: str | None,
    ) -> AsyncIterator[StreamEvent]:
        del body, user, after_event_id
        raise ChatStreamFailure(
            "PROVIDER_UNAVAILABLE",
            True,
            "No tutoring stream Provider is configured.",
        )
        if False:  # pragma: no cover - keeps this an async generator by contract.
            yield DoneEvent(event_id="unreachable")


def get_chat_stream_service(request: Request) -> ChatStreamService:
    service = getattr(request.app.state, "chat_stream_service", None)
    return service if service is not None else _UnavailableChatStreamService()


def _sse(event: StreamEvent) -> str:
    validated = _stream_adapter.validate_python(event)
    event_id = validated.event_id
    if "\r" in event_id or "\n" in event_id:
        raise ChatStreamFailure("PROVIDER_UNAVAILABLE", True, "Invalid stream event identity.")
    payload = _stream_adapter.dump_json(validated).decode()
    return f"id: {event_id}\nevent: {validated.type}\ndata: {payload}\n\n"


@router.post("/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    service: ChatStreamService = Depends(get_chat_stream_service),
) -> StreamingResponse:
    node = db.scalar(
        select(KnowledgeNode)
        .join(CourseCatalog, CourseCatalog.id == KnowledgeNode.course_id)
        .where(
            KnowledgeNode.id == body.node_id,
            KnowledgeNode.course_id == body.course_id,
            CourseCatalog.published.is_(True),
        )
    )
    if node is None or not node.source_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="governed source-bound node not found",
        )
    after_event_id = request.headers.get("last-event-id")
    trace_id = str(request.state.trace_id)

    async def event_source() -> AsyncIterator[str]:
        done = False
        try:
            async for event in service.stream(
                body=body,
                user=user,
                after_event_id=after_event_id,
            ):
                validated = _stream_adapter.validate_python(event)
                yield _sse(validated)
                done = validated.type == "done"
                if done:
                    return
        except ChatStreamFailure as error:
            yield _sse(
                StreamErrorEvent(
                    event_id=f"{trace_id}:error",
                    error=StreamInlineError(
                        code=error.code,
                        message="The tutoring Provider could not complete the stream.",
                        trace_id=trace_id,
                        retryable=error.retryable,
                    ),
                )
            )
        except Exception:
            yield _sse(
                StreamErrorEvent(
                    event_id=f"{trace_id}:error",
                    error=StreamInlineError(
                        code="PROVIDER_UNAVAILABLE",
                        message="The tutoring Provider could not complete the stream.",
                        trace_id=trace_id,
                        retryable=True,
                    ),
                )
            )
        if not done:
            yield _sse(DoneEvent(event_id=f"{trace_id}:done"))

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
