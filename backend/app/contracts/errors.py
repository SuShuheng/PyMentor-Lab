"""Stable, serializable error contract (Pydantic mirror).

Field names and shapes MUST stay byte-identical with ``@pymentor/contracts``
(see ``packages/contracts/src/errors.ts``). The conformance gate
``backend/tests/test_contracts_parity.py`` enforces it against the canonical
JSON Schemas exported from Zod.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(StrEnum):
    """The full set of stable error codes (never renamed)."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    CONTENT_REJECTED = "CONTENT_REJECTED"
    SANDBOX_USER_ERROR = "SANDBOX_USER_ERROR"
    SANDBOX_PLATFORM_ERROR = "SANDBOX_PLATFORM_ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    IPC_INVALID_SENDER = "IPC_INVALID_SENDER"
    IPC_CAPABILITY_DENIED = "IPC_CAPABILITY_DENIED"


class FieldError(BaseModel):
    """A single field-level validation problem, safe to bind to a form field."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1)
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ErrorEnvelope(BaseModel):
    """The wire error envelope. ``details`` is allowlisted, never secret."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    retryable: bool
    field_errors: list[FieldError] | None = None
    details: dict[str, object] | None = None
