"""Middleware: propagate a trace_id across every request.

The trace_id is read from the inbound ``x-trace-id`` header or minted, stored in
``request.state.trace_id`` for handlers/error mapping, and echoed back on the
response so the renderer and logs can correlate (see CONTRACT.md and PRD
REQ-P0-021: "Requests/jobs carry trace IDs").
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import MutableMapping
from time import perf_counter
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_HEADER = "x-trace-id"


class TraceIdMiddleware:
    """ASGI middleware that assigns/forwards a per-request trace id."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        trace_id_raw = headers.get(_HEADER.encode(), b"").decode("ascii", errors="ignore")
        trace_id = trace_id_raw or f"trc_{uuid.uuid4().hex}"
        state: MutableMapping[str, Any] = scope.setdefault("state", {})
        state["trace_id"] = trace_id
        started = perf_counter()
        response_status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = int(message["status"])
                MutableHeaders(scope=message)[_HEADER] = trace_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            from app.config import get_settings

            if get_settings().operational_log_persistence_enabled:
                await asyncio.to_thread(
                    _persist_request_log,
                    state,
                    method=str(scope.get("method", "")),
                    path=str(scope.get("path", "")),
                    status_code=response_status,
                    duration_ms=max(0, int((perf_counter() - started) * 1000)),
                )


def _persist_request_log(
    state: MutableMapping[str, Any],
    *,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
) -> None:
    """Best-effort request logging; telemetry failure never changes the response."""
    from contextlib import suppress

    from app.db import SessionLocal
    from app.observability import record_operational_log

    with suppress(Exception), SessionLocal() as db:
        record_operational_log(
            db,
            tenant_id=state.get("tenant_id"),
            source="ERROR" if status_code >= 500 else "REQUEST",
            level="ERROR" if status_code >= 500 else "INFO",
            message="request failed" if status_code >= 500 else "request completed",
            trace_id=str(state.get("trace_id", "unknown")),
            context={
                "method": method[:16],
                "path": path[:255],
                "status_code": status_code,
                "duration_ms": duration_ms,
                "user_id": None if state.get("user_id") is None else str(state["user_id"]),
            },
        )
        db.commit()
