"""Signed internal client for the Sandbox Supervisor.

The API canonicalizes an execution request, signs it with HMAC-SHA256, posts it
to the Supervisor over a bounded HTTP timeout, validates the response contract,
and maps transport/auth/schema/protocol faults to safe platform categories.

The client never logs request or response bodies. It is the only path the API
uses to reach the Supervisor; production binds the Supervisor to an internal
network and the API never speaks Docker directly.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.contracts.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResponse,
    SandboxResult,
    SandboxTestCase,
)
from sandbox.protocol import (
    MAX_REQUEST_BYTES,
    canonical_json,
    sign_request,
)

SUPERVISOR_TIMEOUT_SECONDS = 30

# A transport callable sends a signed request and returns the raw response.
# Production uses ``httpx.request``; tests inject a fake. The signature mirrors
# the subset of ``httpx.request`` the client relies on.
HttpCaller = Callable[..., httpx.Response]


class SandboxPlatformFailure(Exception):
    """A platform-side fault the API maps to ``PLATFORM_ERROR``.

    ``category`` is a stable string used by operations and audit; it is never
    the raw upstream error string.
    """

    def __init__(self, category: str, message: str) -> None:
        self.category = category
        self.message = message
        super().__init__(f"{category}: {message}")


@dataclass(frozen=True)
class SandboxClientConfig:
    """Connection configuration for the Supervisor."""

    base_url: str
    shared_secret: bytes
    timeout_seconds: float = SUPERVISOR_TIMEOUT_SECONDS


_EXECUTIONS_PATH = "/internal/v1/executions"


def _now_epoch() -> int:
    return int(time.time())


def _build_request_for_phase(
    base: SandboxExecutionRequest,
    *,
    phase_cases: list[SandboxTestCase],
    phase: str,
) -> SandboxExecutionRequest:
    """Return a per-phase execution request with the selected cases.

    Visible and hidden phases run in separate containers, so each call to the
    Supervisor carries only the cases for one phase.
    """

    return base.model_copy(
        update={
            "cases": phase_cases,
            "phase": phase,
        }
    )


def _default_caller(
    method: str,
    url: str,
    *,
    content: bytes,
    headers: dict[str, str],
    timeout: float,
) -> httpx.Response:
    # ``httpx.delete`` does not accept ``content``; use ``httpx.request`` so a
    # signed DELETE body is transmitted correctly.
    return httpx.request(
        method,
        url,
        content=content,
        headers=headers,
        timeout=timeout,
    )


class SandboxClient:
    """HTTP client that signs and sends execution requests to the Supervisor."""

    def __init__(
        self,
        config: SandboxClientConfig,
        *,
        http_caller: HttpCaller = _default_caller,
    ) -> None:
        if len(config.shared_secret) < 32:
            raise SandboxPlatformFailure(
                "SANDBOX_MISCONFIGURED",
                "shared secret must be at least 32 bytes",
            )
        self._config = config
        self._caller = http_caller

    def execute_phase(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxResult:
        """Sign, send, and decode one phase execution; map faults to platform.

        Transport errors, auth failures, non-2xx responses, and schema-invalid
        responses all become :class:`SandboxPlatformFailure`; student-caused
        outcomes arrive inside the validated :class:`SandboxResult`.
        """

        body = canonical_json(request.model_dump(mode="json"))
        if len(body) > MAX_REQUEST_BYTES:
            raise SandboxPlatformFailure(
                "REQUEST_OVERSIZED",
                "execution request exceeds protocol limit",
            )
        timestamp = _now_epoch()
        nonce = f"{request.run_id}-{request.request_id}-{phase_nonce_suffix()}"
        headers = sign_request(
            body,
            method="POST",
            path=_EXECUTIONS_PATH,
            secret=self._config.shared_secret,
            timestamp=timestamp,
            nonce=nonce,
        )
        url = self._config.base_url.rstrip("/") + _EXECUTIONS_PATH
        response = self._send(
            "POST",
            url,
            body=body,
            headers=headers,
        )
        if response.status_code == 401:
            raise SandboxPlatformFailure(
                "SUPERVISOR_AUTH_REJECTED",
                "supervisor rejected the request signature",
            )
        if response.status_code == 413:
            raise SandboxPlatformFailure(
                "REQUEST_OVERSIZED",
                "supervisor rejected an oversized body",
            )
        if response.status_code >= 400:
            raise SandboxPlatformFailure(
                "SUPERVISOR_HTTP_ERROR",
                f"supervisor returned status {response.status_code}",
            )
        try:
            envelope = SandboxExecutionResponse.model_validate_json(response.content)
        except (ValueError, TypeError) as exc:
            raise SandboxPlatformFailure(
                "SUPERVISOR_RESPONSE_INVALID",
                "supervisor response failed schema validation",
            ) from exc
        if envelope.run_id != request.run_id:
            raise SandboxPlatformFailure(
                "SUPERVISOR_RESPONSE_MISMATCH",
                "supervisor response run_id did not match the request",
            )
        return envelope.result

    def cancel(self, run_id: str) -> bool:
        """Send a signed DELETE to cancel/remove labeled containers.

        Cancellation is best-effort; a transport or auth failure is mapped to a
        platform failure so the API can record ``CANCELLED`` consistently.
        """

        path = f"{_EXECUTIONS_PATH}/{run_id}"
        body = canonical_json({})
        timestamp = _now_epoch()
        nonce = f"{run_id}-cancel-{phase_nonce_suffix()}"
        headers = sign_request(
            body,
            method="DELETE",
            path=path,
            secret=self._config.shared_secret,
            timestamp=timestamp,
            nonce=nonce,
        )
        url = self._config.base_url.rstrip("/") + path
        response = self._send("DELETE", url, body=body, headers=headers)
        if response.status_code == 404:
            return False
        if response.status_code == 401:
            raise SandboxPlatformFailure(
                "SUPERVISOR_AUTH_REJECTED",
                "supervisor rejected the cancel signature",
            )
        if response.status_code >= 400:
            raise SandboxPlatformFailure(
                "SUPERVISOR_HTTP_ERROR",
                f"supervisor cancel returned status {response.status_code}",
            )
        return True

    def _send(
        self,
        method: str,
        url: str,
        *,
        body: bytes,
        headers: dict[str, str],
    ) -> httpx.Response:
        try:
            return self._caller(
                method,
                url,
                content=body,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise SandboxPlatformFailure(
                "SUPERVISOR_TIMEOUT",
                "supervisor did not respond within the timeout",
            ) from exc
        except httpx.HTTPError as exc:
            raise SandboxPlatformFailure(
                "SUPERVISOR_UNREACHABLE",
                "supervisor transport error",
            ) from exc


def phase_nonce_suffix() -> str:
    """A short unique suffix so replay protection stays per-call."""

    return secrets.token_hex(8)


def platform_failure_result(run_id: str, category: str, message: str) -> SandboxResult:
    """Build a bounded platform-failure result with no student evidence."""

    return SandboxResult.platform_failure(run_id=run_id, category=category, message=message)


__all__ = [
    "SUPERVISOR_TIMEOUT_SECONDS",
    "HttpCaller",
    "SandboxClient",
    "SandboxClientConfig",
    "SandboxPlatformFailure",
    "_build_request_for_phase",
    "platform_failure_result",
]
