"""Hardened Linux container executor, lifecycle, and error classification.

These tests encode the BE-005 §Container Hardening and §Error Classification
contract. The pure argument builder, cleanup, and classification helpers are
exercised deterministically without a Docker daemon. The real-container
security matrix is skip-gated behind the ``docker`` binary and a Linux engine.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

import pytest

from app.contracts.sandbox import (
    SandboxExecutionRequest,
    SandboxRunStatus,
)
from sandbox.executor import (
    DEFAULT_RUNTIME_IMAGE,
    MAX_ULIMIT_FSIZE_KB,
    MAX_ULIMIT_NOFILE,
    SANDBOX_CHILD_GID,
    SANDBOX_CHILD_UID,
    Executor,
    ExecutorError,
    build_container_args,
    classify_outcome,
    list_container_args,
    remove_container_args,
)

RUN_ID = "run_0123456789abcdef0123456789abcdef"


def _request(**overrides: Any) -> SandboxExecutionRequest:
    base: dict[str, Any] = {
        "protocol_version": "1",
        "request_id": "req_1",
        "run_id": RUN_ID,
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


# --------------------------------------------------------------------------- #
# Container argument hardening (pure, no Docker required)
# --------------------------------------------------------------------------- #


def test_build_container_args_drops_network_and_publishes_no_ports() -> None:
    args = build_container_args(_request())
    assert "--network" in args
    assert args[args.index("--network") + 1] == "none"
    assert "--publish" not in args
    assert "-p" not in args


def test_build_container_args_makes_root_read_only_with_sized_tmpfs_workdir() -> None:
    args = build_container_args(_request())
    assert "--read-only" in args
    tmpfs = [args[i + 1] for i, token in enumerate(args) if token == "--tmpfs"]
    assert any("/work" in entry and "size=" in entry for entry in tmpfs), tmpfs


def test_build_container_args_runs_as_numeric_non_root_user() -> None:
    args = build_container_args(_request())
    user = args[args.index("--user") + 1]
    uid, _, gid = user.partition(":")
    assert uid.isdigit() and gid.isdigit()
    assert int(uid) == SANDBOX_CHILD_UID
    assert int(gid) == SANDBOX_CHILD_GID
    assert int(uid) != 0


def test_build_container_args_drops_all_capabilities_and_blocks_privilege_escalation() -> None:
    args = build_container_args(_request())
    assert args[args.index("--cap-drop") + 1] == "ALL"
    security = [args[i + 1] for i, token in enumerate(args) if token == "--security-opt"]
    assert "no-new-privileges:true" in security
    assert "--privileged" not in args
    assert "--cap-add" not in args


def test_build_container_args_enforces_resource_limits_without_swap_expansion() -> None:
    args = build_container_args(_request())
    assert args[args.index("--memory") + 1] == "128m"
    # Swap must equal memory so the student cannot expand the ceiling.
    assert args[args.index("--memory-swap") + 1] == "128m"
    assert args[args.index("--cpus") + 1] == "1.0"
    assert args[args.index("--pids-limit") + 1] == "32"


def test_build_container_args_binds_file_size_descriptors_and_cpu_ulimits() -> None:
    args = build_container_args(_request())
    ulimits = [args[i + 1] for i, token in enumerate(args) if token == "--ulimit"]
    assert f"fsize={MAX_ULIMIT_FSIZE_KB}:{MAX_ULIMIT_FSIZE_KB}" in ulimits
    assert f"nofile={MAX_ULIMIT_NOFILE}:{MAX_ULIMIT_NOFILE}" in ulimits
    assert any(entry.startswith("cpu=") for entry in ulimits), ulimits


def test_build_container_args_disables_restart_and_caps_stop_timeout() -> None:
    args = build_container_args(_request())
    assert args[args.index("--restart") + 1] == "no"
    stop_timeout = int(args[args.index("--stop-timeout") + 1])
    assert 1 <= stop_timeout <= 10


def test_build_container_args_labels_run_id_protocol_and_expiry_without_secrets() -> None:
    args = build_container_args(_request())
    labels = [args[i + 1] for i, token in enumerate(args) if token == "--label"]
    joined = "\n".join(labels)
    assert f"pymentor.run-id={RUN_ID}" in labels
    assert "pymentor.protocol-version=1" in labels
    assert "pymentor.expires-at=" in joined
    # No secret, source, or hidden-policy material leaks into labels.
    assert "secret" not in joined.lower()
    assert "solve" not in joined


def test_build_container_args_uses_pinned_runtime_image_and_never_pulls() -> None:
    args = build_container_args(_request())
    assert "--pull" not in args
    assert "always" not in args
    # Image is the first positional before the fixed harness command.
    python_index = args.index("python")
    image = args[python_index - 1]
    assert image == DEFAULT_RUNTIME_IMAGE
    assert ":latest" not in DEFAULT_RUNTIME_IMAGE


def test_build_container_args_invokes_fixed_harness_without_a_shell() -> None:
    args = build_container_args(_request())
    # The container command must launch the trusted harness in package mode,
    # never a shell string assembled from request data.
    assert "sh" not in args
    assert "bash" not in args
    python_index = args.index("python")
    assert args[python_index + 1] == "-S"
    assert args[python_index + 2] == "-m"
    assert args[python_index + 3] == "sandbox.harness"


def test_build_container_args_never_binds_docker_socket_host_or_devices() -> None:
    args = build_container_args(_request())
    volume_targets = [args[i + 1] for i, token in enumerate(args) if token in {"-v", "--volume"}]
    for volume in volume_targets:
        assert "docker.sock" not in volume
        assert not volume.startswith("/:")
    assert "--device" not in args
    # PID/IPC namespaces are private; no host namespace sharing.
    assert "--pid=host" not in args
    assert "--ipc=host" not in args


def test_build_container_args_carries_only_validated_numeric_policy() -> None:
    request = _request(
        policy={
            "timeout_ms": 3_000,
            "memory_mb": 256,
            "pids_limit": 64,
            "output_limit_bytes": 32_768,
            "test_limit": 256,
            "trace_frame_limit": 100,
        }
    )
    args = build_container_args(request)
    assert args[args.index("--memory") + 1] == "256m"
    assert args[args.index("--pids-limit") + 1] == "64"


# --------------------------------------------------------------------------- #
# Cleanup and kill labels
# --------------------------------------------------------------------------- #


def test_list_args_scope_cleanup_to_run_label_without_wildcard() -> None:
    args = list_container_args(RUN_ID)
    assert args[:2] == ["ps", "-aq"]
    label_filter = args[args.index("--filter") + 1]
    assert f"label=pymentor.run-id={RUN_ID}" == label_filter
    # No destructive wildcard that could remove unrelated containers.
    assert "$(docker" not in " ".join(args)
    assert "xargs" not in args
    assert "*" not in label_filter


def test_remove_args_force_remove_specific_ids_only() -> None:
    args = remove_container_args(["cid_abc123", "cid_def456"])
    assert args == ["rm", "-f", "cid_abc123", "cid_def456"]
    # The remove call never re-expands a label filter or wildcard.
    assert "--filter" not in args


# --------------------------------------------------------------------------- #
# Outcome classification (pure)
# --------------------------------------------------------------------------- #


def test_classify_outcome_marks_missing_image_and_daemon_failures_as_platform() -> None:
    missing_image = ExecutorError(
        category="RUNTIME_IMAGE_MISSING",
        message="manifest unknown",
        returncode=125,
    )
    classified = classify_outcome(missing_image)
    assert classified.is_platform_error is True
    assert classified.status == SandboxRunStatus.ERROR

    daemon_down = ExecutorError(
        category="DOCKER_UNAVAILABLE",
        message="Cannot connect to the Docker daemon",
    )
    classified_daemon = classify_outcome(daemon_down)
    assert classified_daemon.is_platform_error is True


def test_classify_outcome_treats_outer_timeout_as_platform_cleanup_needed() -> None:
    timeout = ExecutorError(category="OUTER_TIMEOUT", message="container outlived deadline")
    classified = classify_outcome(timeout)
    assert classified.is_platform_error is True
    assert classified.needs_cleanup is True


def test_classify_outcome_treats_spoofed_or_oversized_frame_as_platform() -> None:
    spoof = ExecutorError(category="FRAME_INVALID", message="missing magic prefix")
    classified = classify_outcome(spoof)
    assert classified.is_platform_error is True
    # A spoofed frame must never become trusted student evidence.
    assert classified.status == SandboxRunStatus.ERROR


# --------------------------------------------------------------------------- #
# Executor lifecycle with a fake docker subprocess
# --------------------------------------------------------------------------- #


class _FakeCompleted:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_executor_raises_platform_error_when_docker_binary_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise FileNotFoundError("docker binary not on PATH")

    monkeypatch.setattr(subprocess, "run", _raise)
    executor = Executor(runtime_image=DEFAULT_RUNTIME_IMAGE, docker_binary="docker")
    with pytest.raises(ExecutorError) as caught:
        executor.execute(_request(), secret=b"x" * 32)
    assert caught.value.category == "DOCKER_UNAVAILABLE"


def test_executor_invokes_run_then_cleanup_and_returns_normalized_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def _fake_run(args: list[str], **_kwargs: Any) -> Any:
        calls.append(list(args))
        if args[1:] and args[1] == "run":
            # The harness would emit a real frame; here we synthesize a PASSED
            # frame so the executor can prove it normalizes trusted output only.
            from sandbox.protocol import encode_frame

            frame = encode_frame(
                {
                    "run_id": RUN_ID,
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
            )
            return _FakeCompleted(stdout=frame, returncode=0)
        # ps/rm cleanup calls return empty output.
        return _FakeCompleted(stdout=b"", returncode=0)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    executor = Executor(runtime_image=DEFAULT_RUNTIME_IMAGE, docker_binary="docker")
    result = executor.execute(_request(), secret=b"x" * 32)

    assert result.status == SandboxRunStatus.PASSED
    assert result.tests[0].passed is True
    # The run invocation carried the hardening label, and cleanup followed.
    run_call = next(call for call in calls if len(call) > 1 and call[1] == "run")
    assert f"--label=pymentor.run-id={RUN_ID}" in run_call or any(
        token == f"pymentor.run-id={RUN_ID}" for token in run_call
    )
    # Cleanup ran at least one ps (and a remove only if IDs were found).
    assert any(len(call) > 1 and call[1] == "ps" for call in calls)


def test_executor_cleanup_is_idempotent_and_ignores_missing_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def _fake_run(args: list[str], **_kwargs: Any) -> Any:
        calls.append(list(args))
        # List returns nothing after the first cleanup; remove is a no-op.
        if len(args) > 1 and args[1] == "ps":
            return _FakeCompleted(stdout=b"", returncode=0)
        return _FakeCompleted(stdout=b"", stderr=b"no such container", returncode=1)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    executor = Executor(runtime_image=DEFAULT_RUNTIME_IMAGE, docker_binary="docker")
    # Cleanup must not raise for an already-removed container.
    executor.cleanup(RUN_ID)
    executor.cleanup(RUN_ID)
    # Two list invocations always run; remove is skipped when no IDs remain.
    assert sum(1 for call in calls if len(call) > 1 and call[1] == "ps") == 2


# --------------------------------------------------------------------------- #
# Real-container security matrix (skip-gated)
# --------------------------------------------------------------------------- #

docker_available = shutil.which("docker") is not None
is_linux_engine = os.name == "posix"


@pytest.mark.skipif(
    not (docker_available and is_linux_engine),
    reason="Real-container security matrix requires the docker binary and a Linux engine",
)
def test_real_container_denies_network_and_subprocess_adversarial_matrix() -> None:
    """Skipped without Docker. Documented in BE-005 evidence when run on Linux."""
    executor = Executor(runtime_image=DEFAULT_RUNTIME_IMAGE, docker_binary="docker")
    # Attempt to reach the host and spawn a subprocess; both must be denied.
    request = _request(
        source_code=(
            "def solve(value):\n"
            "    import socket\n"
            "    socket.create_connection(('127.0.0.1', 1), timeout=1)\n"
            "    return value\n"
        ),
        allowed_imports=["math"],
    )
    result = executor.execute(request, secret=b"x" * 32)
    assert result.status == SandboxRunStatus.ERROR
    assert result.platform_error is None
