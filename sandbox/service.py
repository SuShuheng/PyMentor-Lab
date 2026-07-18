"""Signed internal Sandbox Supervisor service.

This is the only component allowed to create job containers. It accepts a
strict signed ``SandboxExecutionRequest`` over ``POST /internal/v1/executions``
and a signed cancel over ``DELETE /internal/v1/executions/{run_id}``.

The Supervisor has no database, Redis, object-store, provider, or JWT
credential. It validates the HMAC signature (timestamp skew, nonce uniqueness,
body digest, constant-time signature) before touching Docker, keeps a bounded
nonce TTL cache and a bounded idempotent response cache keyed by request ID,
and maps protocol/executor/validation faults to redacted internal envelopes.

The service is bound to the internal Compose network only; it exposes no host
port and no public OpenAPI. See
``docs/superpowers/specs/2026-07-17-be-005-sandbox-code-evidence-design.md``
§Supervisor Protocol and §Deployment and Configuration.
"""

from __future__ import annotations

import contextlib
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from typing import cast as typing_cast

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.contracts.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResponse,
    SandboxResult,
)
from sandbox.executor import DEFAULT_RUNTIME_IMAGE, Executor, ExecutorError
from sandbox.protocol import (
    MAX_REQUEST_BYTES,
    MAX_TIMESTAMP_SKEW_SECONDS,
    NonceCache,
    ProtocolAuthenticationError,
    canonical_json,
    sign_request,
    verify_request,
)

EXECUTIONS_PATH = "/internal/v1/executions"
CANCEL_PATH_TEMPLATE = "/internal/v1/executions/{run_id}"
RUN_ID_PATTERN = re.compile(r"run_[0-9a-f]{32}\Z")
RESPONSE_CACHE_CAPACITY = 256
RESPONSE_CACHE_TTL_SECONDS = 300


class SupervisorError(Exception):
    """A redacted, stable Supervisor-level failure."""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class SupervisorSettings:
    """Validated Supervisor configuration.

    The shared secret must be at least 32 bytes; production startup rejects an
    unpinned runtime image or a short secret.
    """

    shared_secret: bytes
    runtime_image: str = DEFAULT_RUNTIME_IMAGE
    docker_binary: str = "docker"
    request_timeout_seconds: int = 30


class ResponseCache:
    """Bounded TTL cache keyed by request ID for idempotent replay.

    A replayed signed request returns the original response without launching a
    second container, matching the design's "existing run label/request ID is an
    idempotent replay" rule.
    """

    def __init__(self, *, ttl_seconds: int, capacity: int) -> None:
        if ttl_seconds < 1 or capacity < 1:
            raise ValueError("response cache ttl and capacity must be positive")
        self.ttl_seconds = ttl_seconds
        self.capacity = capacity
        self._values: OrderedDict[str, tuple[int, SandboxExecutionResponse]] = OrderedDict()

    def get(self, request_id: str, *, now: int) -> SandboxExecutionResponse | None:
        entry = self._values.get(request_id)
        if entry is None:
            return None
        expiry, response = entry
        if expiry <= now:
            self._values.pop(request_id, None)
            return None
        self._values.move_to_end(request_id)
        return response

    def put(self, request_id: str, response: SandboxExecutionResponse, *, now: int) -> None:
        self._values[request_id] = (now + self.ttl_seconds, response)
        self._values.move_to_end(request_id)
        while len(self._values) > self.capacity:
            self._values.popitem(last=False)


@dataclass
class SupervisorState:
    """Mutable per-process state: nonce replay cache and response cache."""

    nonces: NonceCache = field(
        default_factory=lambda: NonceCache(
            ttl_seconds=MAX_TIMESTAMP_SKEW_SECONDS * 2,
            capacity=10_000,
        )
    )
    responses: ResponseCache = field(
        default_factory=lambda: ResponseCache(
            ttl_seconds=RESPONSE_CACHE_TTL_SECONDS,
            capacity=RESPONSE_CACHE_CAPACITY,
        )
    )


def _now() -> int:
    return int(time.time())


def _verify_body_signature(
    body: bytes,
    *,
    method: str,
    path: str,
    headers: dict[str, str],
    settings: SupervisorSettings,
    state: SupervisorState,
    now_fn: Callable[[], int],
) -> None:
    try:
        verify_request(
            body,
            method=method,
            path=path,
            headers=headers,
            secret=settings.shared_secret,
            now=now_fn(),
            nonces=state.nonces,
        )
    except ProtocolAuthenticationError as exc:
        raise SupervisorError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="SANDBOX_AUTH_INVALID",
            message=str(exc),
        ) from exc


def _body_too_large(body: bytes) -> bool:
    return len(body) > MAX_REQUEST_BYTES


def _parse_execution_request(body: bytes) -> SandboxExecutionRequest:
    import json

    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SupervisorError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="SANDBOX_REQUEST_INVALID",
            message="request body is not valid JSON",
        ) from exc
    if not isinstance(parsed, dict):
        raise SupervisorError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="SANDBOX_REQUEST_INVALID",
            message="request body must be a JSON object",
        )
    try:
        return SandboxExecutionRequest.model_validate(parsed)
    except Exception as exc:
        raise SupervisorError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="SANDBOX_REQUEST_INVALID",
            message="execution request failed schema validation",
        ) from exc


def _platform_failure_result(run_id: str, category: str, message: str) -> SandboxResult:
    return SandboxResult.platform_failure(run_id=run_id, category=category, message=message)


def create_supervisor_app(
    settings: SupervisorSettings,
    *,
    state: SupervisorState | None = None,
    executor: Executor | None = None,
    now_fn: Callable[[], int] = _now,
) -> FastAPI:
    """Build the Sandbox Supervisor FastAPI application.

    ``now_fn`` and the optional ``state``/``executor`` injection points exist for
    deterministic tests; production uses the defaults.
    """

    if len(settings.shared_secret) < 32:
        raise SupervisorError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="SANDBOX_MISCONFIGURED",
            message="shared secret must be at least 32 bytes",
        )
    app = FastAPI(
        title="PyMentor Lab Sandbox Supervisor",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.supervisor_settings = settings
    app.state.supervisor_state = state or SupervisorState()
    app.state.supervisor_executor = executor or Executor(
        runtime_image=settings.runtime_image,
        docker_binary=settings.docker_binary,
    )
    app.state.supervisor_now = now_fn

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        # Minimal liveness probe; the supervisor holds no database dependency.
        return {"status": "ok"}

    @app.middleware("http")
    async def reject_oversized_bodies(
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        # Reject bodies over the protocol limit before route handling so an
        # oversized payload never reaches signature verification or Docker.
        if request.method in {"POST", "DELETE", "PUT", "PATCH"}:
            declared = request.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"code": "SANDBOX_REQUEST_TOO_LARGE", "message": "body exceeds limit"},
                )
        return typing_cast(Response, await call_next(request))

    @app.post(EXECUTIONS_PATH, response_model=SandboxExecutionResponse)
    async def execute(request: Request) -> SandboxExecutionResponse:
        body = await request.body()
        if _body_too_large(body):
            raise SupervisorError(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                code="SANDBOX_REQUEST_TOO_LARGE",
                message="body exceeds limit",
            )
        svc_settings: SupervisorSettings = request.app.state.supervisor_settings
        svc_state: SupervisorState = request.app.state.supervisor_state
        _verify_body_signature(
            body,
            method="POST",
            path=EXECUTIONS_PATH,
            headers=dict(request.headers),
            settings=svc_settings,
            state=svc_state,
            now_fn=now_fn,
        )
        execution = _parse_execution_request(body)
        cached = svc_state.responses.get(execution.request_id, now=now_fn())
        if cached is not None:
            return cached
        svc_executor: Executor = request.app.state.supervisor_executor
        try:
            result = svc_executor.execute(execution, secret=svc_settings.shared_secret)
        except ExecutorError as exc:
            # Platform fault: never become student evidence. Return a bounded
            # platform-failure result so the API can finalize PLATFORM_ERROR.
            result = _platform_failure_result(execution.run_id, exc.category, exc.message)
        response = SandboxExecutionResponse(
            protocol_version="1",
            request_id=execution.request_id,
            run_id=execution.run_id,
            result=result,
        )
        svc_state.responses.put(execution.request_id, response, now=now_fn())
        return response

    @app.delete(CANCEL_PATH_TEMPLATE)
    async def cancel(run_id: str, request: Request) -> dict[str, bool]:
        if RUN_ID_PATTERN.fullmatch(run_id) is None:
            # Non-disclosing 404: never confirm whether a run exists.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="execution not found")
        body = await request.body()
        svc_settings: SupervisorSettings = request.app.state.supervisor_settings
        svc_state: SupervisorState = request.app.state.supervisor_state
        _verify_body_signature(
            body,
            method="DELETE",
            path=f"/internal/v1/executions/{run_id}",
            headers=dict(request.headers),
            settings=svc_settings,
            state=svc_state,
            now_fn=now_fn,
        )
        svc_executor: Executor = request.app.state.supervisor_executor
        # Cleanup is best-effort on cancel; the recovery service re-attempts.
        with contextlib.suppress(ExecutorError):
            svc_executor.cleanup(run_id)
        return {"removed": True}

    @app.exception_handler(SupervisorError)
    async def supervisor_error_handler(_request: Request, exc: SupervisorError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "trace_id": _request.headers.get("x-trace-id", ""),
                "retryable": False,
            },
        )

    return app


# --------------------------------------------------------------------------- #
# Helpers for clients/tests
# --------------------------------------------------------------------------- #


def create_app_factory() -> FastAPI:
    """Uvicorn ``--factory`` entrypoint.

    Reads the shared secret, runtime image, and request timeout from the
    environment. Production startup rejects a missing/short secret or an
    unpinned runtime image via :class:`SupervisorError`.
    """

    import os

    secret_text = os.environ.get("PYMENTOR_SANDBOX_SECRET", "")
    secret = secret_text.encode("utf-8")
    if len(secret) < 32:
        raise SupervisorError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="SANDBOX_MISCONFIGURED",
            message="PYMENTOR_SANDBOX_SECRET must be at least 32 bytes",
        )
    runtime_image = os.environ.get("PYMENTOR_SANDBOX_RUNTIME_IMAGE", DEFAULT_RUNTIME_IMAGE)
    if ":latest" in runtime_image or ":" not in runtime_image:
        raise SupervisorError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="SANDBOX_MISCONFIGURED",
            message="runtime image must be pinned to an explicit tag",
        )
    timeout_text = os.environ.get("PYMENTOR_SANDBOX_REQUEST_TIMEOUT_SECONDS", "30")
    try:
        request_timeout = int(timeout_text)
    except ValueError as exc:
        raise SupervisorError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="SANDBOX_MISCONFIGURED",
            message="request timeout must be an integer",
        ) from exc
    settings = SupervisorSettings(
        shared_secret=secret,
        runtime_image=runtime_image,
        request_timeout_seconds=request_timeout,
    )
    return create_supervisor_app(settings)


def sign_execution_body(
    body: bytes,
    *,
    method: str,
    path: str,
    secret: bytes,
    timestamp: int,
    nonce: str,
) -> dict[str, str]:
    """Thin wrapper around ``sign_request`` for client/test convenience."""

    return sign_request(
        body,
        method=method,
        path=path,
        secret=secret,
        timestamp=timestamp,
        nonce=nonce,
    )


def canonical_request_bytes(value: object) -> bytes:
    """Canonical JSON encoding shared by the client and the supervisor."""

    return canonical_json(value)


__all__ = [
    "CANCEL_PATH_TEMPLATE",
    "EXECUTIONS_PATH",
    "Executor",
    "ResponseCache",
    "SupervisorError",
    "SupervisorSettings",
    "SupervisorState",
    "canonical_request_bytes",
    "create_app_factory",
    "create_supervisor_app",
    "sign_execution_body",
]
