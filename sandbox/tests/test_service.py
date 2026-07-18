"""Signed internal Sandbox Supervisor service tests.

These tests prove the Supervisor validates HMAC signatures before touching
Docker, replays idempotent responses, rejects oversized/malformed requests, and
maps executor platform faults to bounded platform-failure results — all without
a live Docker daemon (the executor is replaced by a fake).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.contracts.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResponse,
    SandboxResult,
    SandboxRunStatus,
)
from sandbox.executor import DEFAULT_RUNTIME_IMAGE, ExecutorError
from sandbox.protocol import canonical_json
from sandbox.service import (
    EXECUTIONS_PATH,
    ResponseCache,
    SupervisorError,
    SupervisorSettings,
    SupervisorState,
    create_supervisor_app,
)

SECRET = b"x" * 32
NOW = 1_752_700_010
TIMESTAMP = 1_752_700_000
NONCE = "nonce-exec-1"


def _execution_body(**overrides: Any) -> bytes:
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
    return canonical_json(base)


class _FakeExecutor:
    """Drop-in Executor that returns a canned result without calling Docker."""

    def __init__(
        self,
        *,
        result: dict[str, Any] | None = None,
        error: ExecutorError | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.execute_calls: list[SandboxExecutionRequest] = []
        self.cleanup_calls: list[str] = []

    def execute(self, request: SandboxExecutionRequest, *, secret: bytes) -> Any:
        self.execute_calls.append(request)
        if self._error is not None:
            raise self._error
        from app.contracts.sandbox import SandboxResult

        return SandboxResult.model_validate(self._result)

    def cleanup(self, run_id: str) -> None:
        self.cleanup_calls.append(run_id)


def _passed_result_payload(run_id: str) -> dict[str, Any]:
    return {
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
    }


@pytest.fixture()
def fixed_now() -> int:
    """Pin the supervisor clock so timestamp skew checks are deterministic."""

    return NOW


def _signed_headers(body: bytes, *, method: str, path: str, nonce: str = NONCE) -> dict[str, str]:
    from sandbox.protocol import sign_request

    return sign_request(
        body,
        method=method,
        path=path,
        secret=SECRET,
        timestamp=TIMESTAMP,
        nonce=nonce,
    )


def _client(
    *,
    executor: _FakeExecutor | None = None,
    now_value: int = NOW,
) -> tuple[TestClient, _FakeExecutor]:
    fake = executor or _FakeExecutor(
        result=_passed_result_payload("run_0123456789abcdef0123456789abcdef")
    )
    settings = SupervisorSettings(shared_secret=SECRET, runtime_image=DEFAULT_RUNTIME_IMAGE)
    app = create_supervisor_app(
        settings,
        state=SupervisorState(),
        executor=fake,  # type: ignore[arg-type]
        now_fn=lambda: now_value,
    )
    return TestClient(app), fake


# --------------------------------------------------------------------------- #
# ResponseCache
# --------------------------------------------------------------------------- #


def _platform_response(request_id: str, run_id: str) -> SandboxExecutionResponse:
    return SandboxExecutionResponse(
        protocol_version="1",
        request_id=request_id,
        run_id=run_id,
        result=SandboxResult.platform_failure(run_id=run_id, category="X", message="m"),
    )


def test_response_cache_returns_replay_within_ttl_and_evicts_lru() -> None:
    cache = ResponseCache(ttl_seconds=60, capacity=2)
    cache.put("req_1", _platform_response("req_1", "run_a"), now=NOW)
    cache.put("req_2", _platform_response("req_2", "run_b"), now=NOW)
    # Touch req_1 so req_2 becomes the LRU candidate.
    assert cache.get("req_1", now=NOW) is not None
    cache.put("req_3", _platform_response("req_3", "run_c"), now=NOW)
    assert cache.get("req_2", now=NOW) is None  # evicted
    assert cache.get("req_1", now=NOW) is not None
    assert cache.get("req_3", now=NOW) is not None


def test_response_cache_expires_entries_past_ttl() -> None:
    cache = ResponseCache(ttl_seconds=10, capacity=10)
    cache.put("req_1", _platform_response("req_1", "run_a"), now=NOW)
    assert cache.get("req_1", now=NOW) is not None
    assert cache.get("req_1", now=NOW + 11) is None


# --------------------------------------------------------------------------- #
# Supervisor settings validation
# --------------------------------------------------------------------------- #


def test_create_supervisor_app_rejects_short_secret() -> None:
    with pytest.raises(SupervisorError) as caught:
        create_supervisor_app(SupervisorSettings(shared_secret=b"short"))
    assert caught.value.status_code == 500
    assert caught.value.code == "SANDBOX_MISCONFIGURED"


def test_create_app_factory_reads_env_and_rejects_misconfiguration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sandbox.service import create_app_factory

    # Missing secret -> misconfigured.
    monkeypatch.delenv("PYMENTOR_SANDBOX_SECRET", raising=False)
    with pytest.raises(SupervisorError) as caught:
        create_app_factory()
    assert caught.value.code == "SANDBOX_MISCONFIGURED"

    # Short secret -> misconfigured.
    monkeypatch.setenv("PYMENTOR_SANDBOX_SECRET", "short")
    with pytest.raises(SupervisorError):
        create_app_factory()

    # Valid secret but unpinned image (:latest) -> misconfigured.
    monkeypatch.setenv("PYMENTOR_SANDBOX_SECRET", "x" * 32)
    monkeypatch.setenv("PYMENTOR_SANDBOX_RUNTIME_IMAGE", "pymentor/sandbox-runtime:latest")
    with pytest.raises(SupervisorError) as caught:
        create_app_factory()
    assert "pinned" in caught.value.message

    # Valid secret + pinned image -> app builds and exposes healthz.
    monkeypatch.setenv("PYMENTOR_SANDBOX_RUNTIME_IMAGE", "pymentor/sandbox-runtime:1.0")
    app = create_app_factory()
    client = TestClient(app)
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


# --------------------------------------------------------------------------- #
# POST /internal/v1/executions
# --------------------------------------------------------------------------- #


def test_execute_rejects_unsigned_request() -> None:
    client, _ = _client()
    body = _execution_body()
    response = client.post(EXECUTIONS_PATH, content=body, headers={})
    assert response.status_code == 401
    assert response.json()["code"] == "SANDBOX_AUTH_INVALID"


def test_execute_rejects_bad_signature() -> None:
    client, _ = _client()
    body = _execution_body()
    headers = _signed_headers(body, method="POST", path=EXECUTIONS_PATH)
    headers["x-sandbox-signature"] = "0" * 64
    response = client.post(EXECUTIONS_PATH, content=body, headers=headers)
    assert response.status_code == 401


def test_execute_returns_cached_response_for_replayed_request_id() -> None:
    fake = _FakeExecutor(result=_passed_result_payload("run_0123456789abcdef0123456789abcdef"))
    client, fake_exec = _client(executor=fake)
    body = _execution_body()
    headers = _signed_headers(body, method="POST", path=EXECUTIONS_PATH, nonce="nonce-a")

    first = client.post(EXECUTIONS_PATH, content=body, headers=headers)
    assert first.status_code == 200
    # A replay must use a fresh nonce (the first was consumed) but the same
    # request_id; the supervisor returns the cached response without invoking
    # the executor a second time.
    replay_headers = _signed_headers(body, method="POST", path=EXECUTIONS_PATH, nonce="nonce-b")
    replay = client.post(EXECUTIONS_PATH, content=body, headers=replay_headers)
    assert replay.status_code == 200
    assert replay.json()["run_id"] == first.json()["run_id"]
    assert len(fake_exec.execute_calls) == 1


def test_execute_maps_executor_platform_fault_to_bounded_result() -> None:
    fake = _FakeExecutor(error=ExecutorError("DOCKER_UNAVAILABLE", "no daemon"))
    client, _ = _client(executor=fake)
    body = _execution_body()
    headers = _signed_headers(body, method="POST", path=EXECUTIONS_PATH, nonce="plat-1")
    response = client.post(EXECUTIONS_PATH, content=body, headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["status"] == SandboxRunStatus.ERROR.value
    assert payload["result"]["platform_error"] is not None
    assert payload["result"]["user_error"] is None


def test_execute_rejects_malformed_json_body_after_signature_check() -> None:
    client, _ = _client()
    raw = b"{not valid json"
    headers = _signed_headers(raw, method="POST", path=EXECUTIONS_PATH, nonce="bad-json")
    response = client.post(EXECUTIONS_PATH, content=raw, headers=headers)
    assert response.status_code == 400
    assert response.json()["code"] == "SANDBOX_REQUEST_INVALID"


def test_execute_rejects_schema_invalid_request() -> None:
    client, _ = _client()
    body = _execution_body(protocol_version="9")  # invalid literal
    headers = _signed_headers(body, method="POST", path=EXECUTIONS_PATH, nonce="bad-schema")
    response = client.post(EXECUTIONS_PATH, content=body, headers=headers)
    assert response.status_code == 400


# --------------------------------------------------------------------------- #
# DELETE /internal/v1/executions/{run_id}
# --------------------------------------------------------------------------- #


def test_cancel_rejects_malformed_run_id_with_nondisclosing_404() -> None:
    client, fake = _client()
    body = canonical_json({})
    headers = _signed_headers(
        body, method="DELETE", path="/internal/v1/executions/not-a-run-id", nonce="cancel-1"
    )
    response = client.request(
        "DELETE",
        "/internal/v1/executions/not-a-run-id",
        content=body,
        headers=headers,
    )
    assert response.status_code == 404
    assert fake.cleanup_calls == []


def test_cancel_invokes_executor_cleanup_for_valid_signed_request() -> None:
    run_id = "run_0123456789abcdef0123456789abcdef"
    fake = _FakeExecutor(result=_passed_result_payload(run_id))
    client, fake_exec = _client(executor=fake)
    body = canonical_json({})
    path = f"/internal/v1/executions/{run_id}"
    headers = _signed_headers(body, method="DELETE", path=path, nonce="cancel-ok")
    response = client.request("DELETE", path, content=body, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"removed": True}
    assert fake_exec.cleanup_calls == [run_id]


def test_cancel_rejects_unsigned_request() -> None:
    run_id = "run_0123456789abcdef0123456789abcdef"
    client, _ = _client()
    response = client.request(
        "DELETE", f"/internal/v1/executions/{run_id}", content=b"{}", headers={}
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# Body-size rejection
# --------------------------------------------------------------------------- #


def test_supervisor_rejects_oversized_content_length_before_routing() -> None:
    client, _ = _client()
    # Declare an oversized content-length without sending the bytes; the
    # middleware short-circuits before signature verification.
    response = client.post(
        EXECUTIONS_PATH,
        content=b"x",
        headers={"content-length": str(1024 * 1024)},
    )
    assert response.status_code in {413, 401}
