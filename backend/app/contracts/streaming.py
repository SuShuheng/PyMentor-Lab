"""Streaming contracts (Pydantic mirror).

Mirror of ``packages/contracts/src/streaming.ts``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1, max_length=20_000)


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: UUID
    node_id: UUID
    messages: list[ChatMessage] = Field(min_length=1, max_length=64)
    stream: Literal[True] = True


class ToolCallDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    id: str | None = None
    name: str | None = None
    arguments: str | None = None


class ChatCompletionChunk(BaseModel):
    """OpenAI Chat Completions-compatible streaming chunk."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    delta_content: str | None = None
    delta_reasoning: str | None = None
    delta_tool_calls: list[ToolCallDelta] | None = None
    model: str | None = None
    timestamp: str = Field(min_length=1)


class StreamInlineError(BaseModel):
    """Inline error carried on the ``error`` stream event."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    retryable: bool


class StreamEventType(StrEnum):
    CONTENT_DELTA = "content_delta"
    REASONING_DELTA = "reasoning_delta"
    TOOL_CALL_DELTA = "tool_call_delta"
    PROGRESS = "progress"
    ERROR = "error"
    DONE = "done"


class _StreamEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)


class ContentDeltaEvent(_StreamEventBase):
    type: Literal[StreamEventType.CONTENT_DELTA] = StreamEventType.CONTENT_DELTA
    chunk: ChatCompletionChunk


class ReasoningDeltaEvent(_StreamEventBase):
    type: Literal[StreamEventType.REASONING_DELTA] = StreamEventType.REASONING_DELTA
    chunk: ChatCompletionChunk


class ToolCallDeltaEvent(_StreamEventBase):
    type: Literal[StreamEventType.TOOL_CALL_DELTA] = StreamEventType.TOOL_CALL_DELTA
    chunk: ChatCompletionChunk


class ProgressEvent(_StreamEventBase):
    type: Literal[StreamEventType.PROGRESS] = StreamEventType.PROGRESS
    message: str | None = None
    percent: float | None = Field(default=None, ge=0, le=100)


class StreamErrorEvent(_StreamEventBase):
    type: Literal[StreamEventType.ERROR] = StreamEventType.ERROR
    error: StreamInlineError


class DoneEvent(_StreamEventBase):
    type: Literal[StreamEventType.DONE] = StreamEventType.DONE


# Pydantic v2 discriminated union: the renderer dispatches on ``type``.
StreamEvent = Annotated[
    ContentDeltaEvent
    | ReasoningDeltaEvent
    | ToolCallDeltaEvent
    | ProgressEvent
    | StreamErrorEvent
    | DoneEvent,
    Field(discriminator="type"),
]
