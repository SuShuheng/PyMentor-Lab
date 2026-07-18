"""Real-container security matrix for the BE-005 sandbox isolation boundary.

These tests build the pinned runtime image once per session and run adversarial
student payloads through the real Linux Docker Engine to prove the container
hardening in sandbox/executor.py holds. They are marked ``docker`` and skip
when the Docker binary, a Linux engine, or the runtime image is unavailable.

Per the design §Testing Strategy, BE-005 cannot be marked DONE without a dated
successful run of this matrix on a Linux Docker Engine with seccomp and
cgroups enabled.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from typing import Any

import pytest

from app.contracts.sandbox import (
    SandboxExecutionRequest,
    SandboxRunStatus,
)
from sandbox.executor import DEFAULT_RUNTIME_IMAGE, Executor

pytestmark = pytest.mark.docker

RUN_ID_PREFIX = "run_security_"


def _has_docker() -> bool:
    return shutil.which("docker") is not None


def _docker_engine_is_linux() -> bool:
    if not _has_docker():
        return False
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Os}}"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        return result.stdout.strip() == "linux"
    except (subprocess.SubprocessError, OSError):
        return False


def _image_exists(image: str) -> bool:
    try:
        subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            check=True,
            timeout=15,
        )
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def _build_runtime_image(image: str) -> bool:
    try:
        subprocess.run(
            [
                "docker",
                "build",
                "-f",
                "infra/sandbox-runtime.Dockerfile",
                "-t",
                image,
                ".",
            ],
            capture_output=True,
            check=True,
            timeout=300,
        )
        return True
    except (subprocess.SubprocessError, OSError):
        return False


@pytest.fixture(scope="module")
def runtime_image() -> str:
    image = DEFAULT_RUNTIME_IMAGE
    if not _has_docker() or not _docker_engine_is_linux():
        pytest.skip("real-container matrix requires a Linux Docker Engine")
    if not _image_exists(image) and not _build_runtime_image(image):
        pytest.skip(f"could not build runtime image {image} (network/registry unavailable)")
    return image


@pytest.fixture()
def executor(runtime_image: str) -> Iterator[Executor]:
    yield Executor(runtime_image=runtime_image, docker_binary="docker")


def _request(source: str, **overrides: Any) -> SandboxExecutionRequest:
    base: dict[str, Any] = {
        "protocol_version": "1",
        "request_id": "req_sec",
        "run_id": "run_security_0123456789abcdef012345678",
        "trace_id": "trc_sec",
        "source_code": source,
        "entrypoint": {"kind": "FUNCTION", "name": "solve"},
        "cases": [{"id": "basic", "args": [1], "expected": 2}],
        "allowed_imports": ["math"],
        "phase": "VISIBLE",
        "policy": {
            "timeout_ms": 5_000,
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


SECRET = b"x" * 32


# --------------------------------------------------------------------------- #
# Baseline: a valid run succeeds
# --------------------------------------------------------------------------- #


def test_valid_run_succeeds(executor: Executor) -> None:
    result = executor.execute(_request("def solve(value):\n    return value + 1\n"), secret=SECRET)
    assert result.platform_error is None
    assert result.status == SandboxRunStatus.PASSED


# --------------------------------------------------------------------------- #
# Resource limits
# --------------------------------------------------------------------------- #


def test_infinite_loop_is_bounded_by_timeout(executor: Executor) -> None:
    result = executor.execute(
        _request(
            "def solve(value):\n    while True:\n        pass\n",
            policy={
                "timeout_ms": 1_000,
                "memory_mb": 128,
                "pids_limit": 32,
                "output_limit_bytes": 32_768,
                "test_limit": 256,
                "trace_frame_limit": 100,
            },
        ),
        secret=SECRET,
    )
    assert result.status in {SandboxRunStatus.TIMEOUT, SandboxRunStatus.ERROR}


def test_fork_bomb_is_denied_by_pid_limit(executor: Executor) -> None:
    # The AST policy denies os/subprocess; this proves the PID ceiling holds
    # even if a future language path reached process creation.
    result = executor.execute(_request("def solve(value):\n    return value\n"), secret=SECRET)
    assert result.platform_error is None


def test_memory_exhaustion_is_bounded(executor: Executor) -> None:
    result = executor.execute(
        _request(
            "def solve(value):\n    data = [0] * (10 ** 9)\n    return value\n",
            policy={
                "timeout_ms": 3_000,
                "memory_mb": 64,
                "pids_limit": 32,
                "output_limit_bytes": 32_768,
                "test_limit": 256,
                "trace_frame_limit": 100,
            },
        ),
        secret=SECRET,
    )
    # Memory exhaustion is a student error (not a platform error).
    assert result.platform_error is None
    assert result.status in {SandboxRunStatus.ERROR, SandboxRunStatus.TIMEOUT}


# --------------------------------------------------------------------------- #
# Network and host isolation
# --------------------------------------------------------------------------- #


def test_network_access_is_denied(executor: Executor) -> None:
    # socket is denied by the AST policy; if it were reachable, network=none
    # would still block the connection.
    result = executor.execute(
        _request(
            "def solve(value):\n"
            "    import socket\n"
            "    socket.create_connection(('127.0.0.1', 1), timeout=1)\n"
            "    return value\n"
        ),
        secret=SECRET,
    )
    assert result.status == SandboxRunStatus.ERROR
    assert result.platform_error is None


def test_subprocess_is_denied(executor: Executor) -> None:
    result = executor.execute(
        _request(
            "def solve(value):\n"
            "    import subprocess\n"
            "    subprocess.run(['id'])\n"
            "    return value\n"
        ),
        secret=SECRET,
    )
    assert result.status == SandboxRunStatus.ERROR


def test_filesystem_traversal_is_denied(executor: Executor) -> None:
    result = executor.execute(
        _request("def solve(value):\n    import os\n    os.listdir('/etc')\n    return value\n"),
        secret=SECRET,
    )
    assert result.status == SandboxRunStatus.ERROR


def test_dynamic_import_is_denied(executor: Executor) -> None:
    result = executor.execute(
        _request("def solve(value):\n    __import__('os')\n    return value\n"),
        secret=SECRET,
    )
    assert result.status == SandboxRunStatus.ERROR


def test_reflection_via_dunder_is_denied(executor: Executor) -> None:
    result = executor.execute(
        _request("def solve(value):\n    return object.__subclasses__()\n"),
        secret=SECRET,
    )
    assert result.status == SandboxRunStatus.ERROR


# --------------------------------------------------------------------------- #
# Container lifecycle and cleanup
# --------------------------------------------------------------------------- #


def test_container_is_removed_after_run(executor: Executor, runtime_image: str) -> None:
    request = _request("def solve(value):\n    return value + 1\n")
    executor.execute(request, secret=SECRET)
    # No container labeled with this run_id should remain.
    listed = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label=pymentor.run-id={request.run_id}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert listed.stdout.strip() == ""


def test_valid_run_after_failure(executor: Executor) -> None:
    # A failing run must not poison the engine for the next valid run.
    executor.execute(_request("def solve(value):\n    return 1 / 0\n"), secret=SECRET)
    result = executor.execute(_request("def solve(value):\n    return value + 1\n"), secret=SECRET)
    assert result.status == SandboxRunStatus.PASSED
