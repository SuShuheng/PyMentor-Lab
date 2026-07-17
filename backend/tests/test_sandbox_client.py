"""Signed Sandbox Supervisor client transport and fault mapping tests.

The client accepts an injectable ``http_caller`` so these tests exercise the
signing, response validation, and fault-mapping logic without a live network or
a running Supervisor.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.contracts.sandbox import (
    SandboxExecutionRequest,
    SandboxRunStatus,
)
from app.sandbox_client import (
    SandboxClient,
    SandboxClientConfig,
    SandboxPlatformFailure,
    platform_failure_result,
)
from sandbox.protocol import canonical_json

SECRET = b"x" * 32
BASE_URL = "http://sandbox:8090"


def _request(**overrides: Any) -> SandboxExecutionRequest:
    base: dict[str, Any] = {
        "protocol_version": "1",
        "request_id": "req_1",
        "run_id": "run_0123456789abcdef0123456789abcdef",
        "trace_id": "trc_1",
        "source_code": "def solve(value):\n    return value + 1\n",
        "entrypoint": {"kind": "FUNCTION", "name": "solve"},
        "cases": [{"id": "basic", "args": [1], "expected": 2}],
        "allowed_imports": ["math"],
        "phase": "VISIBLE",
        "policy": {
            "timeout_ms": 2_000,
            "memory_mb": 128,
            "pids_limit": 32,
            "output_limit_bytes": 32_768,
            "test_limit": 256,
            "trace_frame_limit": 100,
        },
        "trace_enabled": False,
    }
    base.update(overrides)
    return SandboxExecutionRequest.model_validate(base)


def _passed_response_payload(run_id: str) -> bytes:
    payload = {
        "protocol_version": "1",
        "request_id": "req_1",
        "run_id": run_id,
        "result": {
            "run_id": run_id,
            "status": "PASSED",
            "passed": True,
            "stdout": "",
            "stderr": "",
            "tests": [
                {
                    "case_id": "basic",
                    "display_name": "basic",
                    "visibility": "VISIBLE",
                    "comparison": "EQUAL",
                    "transfer": False,
                    "passed": True,
                    "stdout": "",
                    "stderr": "",
                    "duration_ms": 12,
                }
            ],
            "trace_frames": None,
            "resource_usage": {
                "cpu_ms": 10,
                "wall_ms": 12,
                "peak_memory_kb": 1024,
                "exit_code": 0,
            },
            "stdout_truncated": False,
            "stderr_truncated": False,
            "trace_truncated": False,
            "user_error": None,
            "platform_error": None,
        },
    }
    return canonical_json(payload)


def _client(caller) -> SandboxClient:
    config = SandboxClientConfig(base_url=BASE_URL, shared_secret=SECRET, timeout_seconds=5.0)
    return SandboxClient(config, http_caller=caller)


class _RecordingCaller:
    """Captures the last request for assertions and returns a fixed response."""

    def __init__(self, *, response: httpx.Response) -> None:
        self.response = response
        self.last: httpx.Request | None = None

    def __call__(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        # ``timeout`` is a caller-level concern, not a Request field.
        kwargs.pop("timeout", None)
        self.last = httpx.Request(method, url, **kwargs)
        return self.response


def _raise(exc: BaseException):
    def _caller(*_args: Any, **_kwargs: Any) -> httpx.Response:
        raise exc

    return _caller


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


def test_client_rejects_short_secret() -> None:
    with pytest.raises(SandboxPlatformFailure) as caught:
        SandboxClient(SandboxClientConfig(base_url=BASE_URL, shared_secret=b"short"))
    assert caught.value.category == "SANDBOX_MISCONFIGURED"


# --------------------------------------------------------------------------- #
# execute_phase
# --------------------------------------------------------------------------- #


def test_execute_phase_returns_validated_result_on_success() -> None:
    run_id = "run_0123456789abcdef0123456789abcdef"
    caller = _RecordingCaller(
        response=httpx.Response(200, content=_passed_response_payload(run_id))
    )
    client = _client(caller)
    result = client.execute_phase(_request())
    assert result.status == SandboxRunStatus.PASSED
    assert result.tests[0].passed is True
    # The signed request targeted the executions path and carried HMAC headers.
    assert caller.last is not None
    assert caller.last.url.path == "/internal/v1/executions"
    assert "x-sandbox-signature" in {k.lower() for k in caller.last.headers}


def test_execute_phase_maps_timeout_to_platform_failure() -> None:
    client = _client(_raise(httpx.TimeoutException("slow")))
    with pytest.raises(SandboxPlatformFailure) as caught:
        client.execute_phase(_request())
    assert caught.value.category == "SUPERVISOR_TIMEOUT"


def test_execute_phase_maps_transport_error_to_platform_failure() -> None:
    client = _client(_raise(httpx.ConnectError("no route")))
    with pytest.raises(SandboxPlatformFailure) as caught:
        client.execute_phase(_request())
    assert caught.value.category == "SUPERVISOR_UNREACHABLE"


def test_execute_phase_maps_auth_rejection_to_platform_failure() -> None:
    client = _client(
        _RecordingCaller(response=httpx.Response(401, content=b'{"code":"SANDBOX_AUTH_INVALID"}'))
    )
    with pytest.raises(SandboxPlatformFailure) as caught:
        client.execute_phase(_request())
    assert caught.value.category == "SUPERVISOR_AUTH_REJECTED"


def test_execute_phase_maps_oversized_rejection_to_platform_failure() -> None:
    client = _client(_RecordingCaller(response=httpx.Response(413, content=b"{}")))
    with pytest.raises(SandboxPlatformFailure) as caught:
        client.execute_phase(_request())
    assert caught.value.category == "REQUEST_OVERSIZED"


def test_execute_phase_maps_generic_http_error_to_platform_failure() -> None:
    client = _client(_RecordingCaller(response=httpx.Response(500, content=b"{}")))
    with pytest.raises(SandboxPlatformFailure) as caught:
        client.execute_phase(_request())
    assert caught.value.category == "SUPERVISOR_HTTP_ERROR"


def test_execute_phase_rejects_response_with_mismatched_run_id() -> None:
    client = _client(
        _RecordingCaller(
            response=httpx.Response(
                200, content=_passed_response_payload("run_deadbeefdeadbeefdeadbeefdeadbeef")
            )
        )
    )
    with pytest.raises(SandboxPlatformFailure) as caught:
        client.execute_phase(_request())
    assert caught.value.category == "SUPERVISOR_RESPONSE_MISMATCH"


def test_execute_phase_rejects_schema_invalid_response() -> None:
    client = _client(
        _RecordingCaller(response=httpx.Response(200, content=b'{"protocol_version":"1"}'))
    )
    with pytest.raises(SandboxPlatformFailure) as caught:
        client.execute_phase(_request())
    assert caught.value.category == "SUPERVISOR_RESPONSE_INVALID"


# --------------------------------------------------------------------------- #
# cancel
# --------------------------------------------------------------------------- #


def test_cancel_returns_true_on_success() -> None:
    run_id = "run_0123456789abcdef0123456789abcdef"
    caller = _RecordingCaller(response=httpx.Response(200, content=b'{"removed":true}'))
    client = _client(caller)
    assert client.cancel(run_id) is True
    assert caller.last is not None
    assert caller.last.method == "DELETE"
    assert caller.last.url.path == f"/internal/v1/executions/{run_id}"


def test_cancel_returns_false_on_404() -> None:
    run_id = "run_0123456789abcdef0123456789abcdef"
    client = _client(_RecordingCaller(response=httpx.Response(404, content=b"{}")))
    assert client.cancel(run_id) is False


def test_cancel_maps_transport_error_to_platform_failure() -> None:
    run_id = "run_0123456789abcdef0123456789abcdef"
    client = _client(_raise(httpx.ConnectError("down")))
    with pytest.raises(SandboxPlatformFailure) as caught:
        client.cancel(run_id)
    assert caught.value.category == "SUPERVISOR_UNREACHABLE"


def test_cancel_maps_auth_rejection_to_platform_failure() -> None:
    run_id = "run_0123456789abcdef0123456789abcdef"
    client = _client(_RecordingCaller(response=httpx.Response(401, content=b"{}")))
    with pytest.raises(SandboxPlatformFailure) as caught:
        client.cancel(run_id)
    assert caught.value.category == "SUPERVISOR_AUTH_REJECTED"


# --------------------------------------------------------------------------- #
# platform_failure_result helper
# --------------------------------------------------------------------------- #


def test_platform_failure_result_is_bounded_without_student_evidence() -> None:
    result = platform_failure_result("run_x", "DOCKER_UNAVAILABLE", "no daemon")
    assert result.status == SandboxRunStatus.ERROR
    assert result.platform_error is not None
    assert result.user_error is None
    assert result.tests == []
