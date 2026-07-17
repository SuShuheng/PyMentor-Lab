"""Error handling: map FastAPI/Pydantic failures to the stable ErrorEnvelope.

Every error response uses the wire contract from ``app.contracts.errors`` so the
renderer, worker, and generated client all see the same shape. ``trace_id`` is
always present and ``details`` never carries secrets, raw prompts, stack traces,
database keys, or local paths (see CONTRACT.md "Errors").
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.contracts.errors import ErrorCode, ErrorEnvelope, FieldError


def _new_trace_id(request: Request) -> str:
    """Use the inbound trace id if provided, else mint one."""

    existing = request.headers.get("x-trace-id")
    if existing:
        return existing
    return f"trc_{uuid.uuid4().hex}"


def _envelope(
    *,
    code: ErrorCode,
    message: str,
    trace_id: str,
    retryable: bool,
    status_code: int,
    field_errors: list[FieldError] | None = None,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    envelope = ErrorEnvelope(
        code=code,
        message=message,
        trace_id=trace_id,
        retryable=retryable,
        field_errors=field_errors,
        details=details,
    )
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


def install_error_handlers(app: FastAPI) -> None:
    """Register the stable error-envelope handlers on the app."""

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        trace_id = _new_trace_id(request)
        field_errors: list[FieldError] = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err.get("loc", []) if part != "body")
            field_errors.append(
                FieldError(
                    field=loc or "body",
                    code=err.get("type", "invalid"),
                    message=err.get("msg", "invalid value"),
                )
            )
        return _envelope(
            code=ErrorCode.VALIDATION_ERROR,
            message="Request validation failed.",
            trace_id=trace_id,
            retryable=False,
            status_code=422,
            field_errors=field_errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        trace_id = _new_trace_id(request)
        code, retryable = _map_http_status(exc.status_code)
        return _envelope(
            code=code,
            message=str(exc.detail) if exc.detail else code.value,
            trace_id=trace_id,
            retryable=retryable,
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Last-resort handler: never leak the exception text to the client."""

        trace_id = _new_trace_id(request)
        return _envelope(
            code=ErrorCode.INTERNAL_ERROR,
            message="An unexpected error occurred.",
            trace_id=trace_id,
            retryable=False,
            status_code=500,
            details={"trace_id": trace_id},
        )


def _map_http_status(status_code: int) -> tuple[ErrorCode, bool]:
    if status_code == 401:
        return ErrorCode.AUTH_REQUIRED, False
    if status_code == 403:
        return ErrorCode.FORBIDDEN, False
    if status_code == 404:
        return ErrorCode.NOT_FOUND, False
    if status_code == 409:
        return ErrorCode.CONFLICT, False
    if status_code == 429:
        return ErrorCode.RATE_LIMITED, True
    if status_code in (400, 422):
        return ErrorCode.VALIDATION_ERROR, False
    return ErrorCode.INTERNAL_ERROR, False
