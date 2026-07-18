"""Tests for the FastAPI system skeleton: /health, /system/ping, ErrorEnvelope."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

import app.api.health as health_module
from app.agent_event_consumer import AgentEventConsumerHealth
from app.config import Settings
from app.errors import install_error_handlers
from app.main import create_app
from app.middleware import TraceIdMiddleware


def test_health_returns_ok_envelope() -> None:
    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"]
    assert body["version"]
    assert body["timestamp"]


def test_system_ping_returns_ok() -> None:
    """The public ping endpoint powers the renderer server-address test (§7.2)."""
    client = TestClient(create_app())
    response = client.get("/system/ping")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["service"]
    assert body["timestamp"]


def test_readiness_degrades_when_enabled_agent_consumer_is_not_ready(monkeypatch) -> None:
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: Settings(agent_event_consumer_enabled=True),
    )
    app = create_app()
    app.state.agent_event_consumer_health = AgentEventConsumerHealth(alive=True, ready=False)
    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_trace_id_is_echoed_when_absent() -> None:
    """A minted trace_id must appear on the response header."""
    client = TestClient(create_app())
    response = client.get("/health")

    trace_id = response.headers.get("x-trace-id")
    assert trace_id is not None
    assert trace_id.startswith("trc_")


def test_trace_id_is_forwarded_when_provided() -> None:
    """An inbound trace_id is preserved end-to-end."""
    client = TestClient(create_app())
    response = client.get("/health", headers={"x-trace-id": "trc_fixed"})

    assert response.headers["x-trace-id"] == "trc_fixed"


def test_unknown_route_returns_not_found_envelope() -> None:
    """404s use the stable ErrorEnvelope, not a bare Starlette body."""
    client = TestClient(create_app())
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert body["trace_id"]
    assert body["trace_id"] == response.headers["x-trace-id"]
    assert body["retryable"] is False


def test_unhandled_error_returns_internal_error_envelope() -> None:
    """A 500 never leaks the raw exception text to the client."""
    boom = FastAPI()
    boom.add_middleware(TraceIdMiddleware)
    install_error_handlers(boom)
    r = APIRouter()

    @r.get("/boom")
    async def _boom() -> None:
        raise RuntimeError("secret stack detail")

    boom.include_router(r)
    response = TestClient(boom, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["retryable"] is False
    assert "secret stack detail" not in response.text
    assert body["trace_id"]
    assert body["trace_id"] == response.headers["x-trace-id"]
