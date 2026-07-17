"""Middleware: propagate a trace_id across every request.

The trace_id is read from the inbound ``x-trace-id`` header or minted, stored in
``request.state.trace_id`` for handlers/error mapping, and echoed back on the
response so the renderer and logs can correlate (see CONTRACT.md and PRD
REQ-P0-021: "Requests/jobs carry trace IDs").
"""

from __future__ import annotations

import uuid
from collections.abc import MutableMapping
from typing import Any

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

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"].append((_HEADER.encode(), trace_id.encode("ascii")))
            await send(message)

        await self.app(scope, receive, send_wrapper)
