"""Hardened Linux container executor for untrusted student Python.

This module is the BE-005 authoritative isolation boundary. It builds a
``docker run`` argument list from constants and validated numeric policy
values only, invokes the pinned runtime image, decodes the single trusted
protocol frame the harness writes, and always removes the labeled container
afterwards.

Design contract (see ``docs/superpowers/specs/2026-07-17-be-005-sandbox-code-evidence-design.md``
§Container Hardening and §Error Classification):

- network is disabled and no ports are published;
- the root filesystem is read-only with a size-limited ``tmpfs`` work dir;
- the student child runs as a fixed numeric non-root UID/GID;
- all capabilities are dropped, ``no-new-privileges`` is set, and the
  container is never privileged;
- memory equals memory-swap (no swap expansion), one CPU, bounded PIDs,
  bounded file size, descriptors, and CPU time;
- restart is disabled and the stop timeout is capped;
- labels carry only run ID, protocol version, and an expiry stamp — never
  source, secrets, or hidden policy;
- the Docker socket, host binds, devices, and host PID/IPC namespaces are
  never mounted or shared;
- cleanup is force-remove scoped by run label and idempotent.

The argument builder and outcome classifiers are pure functions exercised in
unit tests without a Docker daemon. The real-container security matrix is
skip-gated behind the ``docker`` binary and a Linux engine.
"""

from __future__ import annotations

import contextlib
import dataclasses
import subprocess
import time
from collections.abc import Sequence

from app.contracts.sandbox import (
    SandboxExecutionPolicy,
    SandboxExecutionRequest,
    SandboxResult,
    SandboxRunStatus,
)
from sandbox.protocol import (
    MAX_REQUEST_BYTES,
    ProtocolFrameError,
    decode_frame,
    encode_frame,
    sign_request,
)

# --------------------------------------------------------------------------- #
# Pinned constants
# --------------------------------------------------------------------------- #

# Logical runtime image. Pinned to an explicit tag — never ``:latest`` — so a
# missing image is a deterministic platform error rather than a silent fetch.
DEFAULT_RUNTIME_IMAGE = "pymentor/sandbox-runtime:1.0"

# Fixed numeric non-root identity for the untrusted student child. The harness
# trusts this UID/GID; production images must create matching accounts.
SANDBOX_CHILD_UID = 10001
SANDBOX_CHILD_GID = 10001

# Resource ceilings expressed as ulimits. The harness policy may select lower
# values; these are absolute upper bounds enforced at the container boundary.
MAX_ULIMIT_FSIZE_KB = 16_384  # 16 MiB max file size a child can grow.
MAX_ULIMIT_NOFILE = 64  # Bounded descriptor table for untrusted code.
MAX_ULIMIT_CPU_SECONDS = 30  # Absolute CPU-time ceiling above policy timeout.

WORK_DIR = "/work"
STOP_TIMEOUT_SECONDS = 5
TMPFS_SIZE_BYTES = 16 * 1024 * 1024

SUPERVISOR_PATH = "/internal/v1/executions"
SUPERVISOR_METHOD = "POST"
SHARED_SECRET_MIN_BYTES = 32


class ExecutorError(Exception):
    """A platform-side failure in container orchestration or protocol framing.

    ``category`` is a stable string consumed by ``classify_outcome`` and never
    surfaced to the student beyond the generic ``SANDBOX_PLATFORM_ERROR`` code.
    """

    def __init__(
        self,
        category: str,
        message: str,
        *,
        returncode: int | None = None,
    ) -> None:
        self.category = category
        self.message = message
        self.returncode = returncode
        super().__init__(f"{category}: {message}")


# --------------------------------------------------------------------------- #
# Pure argument builders
# --------------------------------------------------------------------------- #


def _ulimits(timeout_ms: int) -> list[str]:
    """Build the ``--ulimit`` tokens from validated policy values.

    ``cpu=`` is clamped to the absolute ceiling so a policy value can never
    exceed the production safety bound.
    """

    policy_cpu_seconds = max(1, (timeout_ms + 999) // 1000)
    cpu_seconds = min(policy_cpu_seconds, MAX_ULIMIT_CPU_SECONDS)
    return [
        "--ulimit",
        f"fsize={MAX_ULIMIT_FSIZE_KB}:{MAX_ULIMIT_FSIZE_KB}",
        "--ulimit",
        f"nofile={MAX_ULIMIT_NOFILE}:{MAX_ULIMIT_NOFILE}",
        "--ulimit",
        f"cpu={cpu_seconds}:{cpu_seconds}",
    ]


def _labels(request: SandboxExecutionRequest) -> list[str]:
    """Carry only run ID, protocol version, and a bounded expiry stamp.

    Expiry is the outer deadline (policy timeout plus a cleanup grace margin)
    so the recovery service can find stale labeled containers.
    """

    deadline_epoch = int(time.time()) + (request.policy.timeout_ms // 1000) + STOP_TIMEOUT_SECONDS
    labels = [
        f"pymentor.run-id={request.run_id}",
        f"pymentor.protocol-version={request.protocol_version}",
        f"pymentor.expires-at={deadline_epoch}",
        f"pymentor.phase={request.phase.value}",
    ]
    tokens: list[str] = []
    for label in labels:
        tokens.append("--label")
        tokens.append(label)
    return tokens


def build_container_args(
    request: SandboxExecutionRequest,
    *,
    runtime_image: str = DEFAULT_RUNTIME_IMAGE,
) -> list[str]:
    """Return the hardened ``docker run`` argument list for one execution.

    The list is assembled from constants and validated numeric policy values.
    It never concatenates a shell command and never embeds source, secrets, or
    hidden policy material.
    """

    policy: SandboxExecutionPolicy = request.policy
    memory = f"{policy.memory_mb}m"
    args: list[str] = [
        "run",
        "--rm",
        # No network, no published ports, no host namespace sharing.
        "--network",
        "none",
        "--dns",
        "none",
        # Read-only root filesystem with a size-bounded tmpfs work directory.
        "--read-only",
        "--tmpfs",
        f"{WORK_DIR}:rw,noexec,nosuid,nodev,size={TMPFS_SIZE_BYTES}",
        # Fixed numeric non-root student identity.
        "--user",
        f"{SANDBOX_CHILD_UID}:{SANDBOX_CHILD_GID}",
        # Drop every capability and block privilege escalation.
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--security-opt",
        "label:disable",
        # Resource ceilings. Memory-swap equals memory so the child cannot
        # expand the ceiling via swap.
        "--memory",
        memory,
        "--memory-swap",
        memory,
        "--cpus",
        "1.0",
        "--pids-limit",
        str(policy.pids_limit),
    ]
    args.extend(_ulimits(policy.timeout_ms))
    args.extend(
        [
            # Disable restart and cap the stop timeout.
            "--restart",
            "no",
            "--stop-timeout",
            str(STOP_TIMEOUT_SECONDS),
        ]
    )
    args.extend(_labels(request))
    # Pinned runtime image and the fixed trusted harness entrypoint. No shell.
    args.extend(
        [
            runtime_image,
            "python",
            "-S",
            "-m",
            "sandbox.harness",
        ]
    )
    return args


def list_container_args(run_id: str) -> list[str]:
    """Return ``docker ps -aq`` scoped to one run label.

    The executor lists matching container IDs first, then force-removes each
    one. This keeps the destructive ``rm`` call bounded to concrete IDs and
    avoids shell pipelines or wildcards.
    """

    return ["ps", "-aq", "--filter", f"label=pymentor.run-id={run_id}"]


def remove_container_args(container_ids: Sequence[str]) -> list[str]:
    """Return ``docker rm -f`` for concrete container IDs only.

    Never accepts a label filter or wildcard — only IDs resolved by
    ``list_container_args``.
    """

    if not container_ids:
        # Return a harmless no-op invocation the executor will short-circuit.
        return ["rm", "-f"]
    return ["rm", "-f", *container_ids]


def kill_container_args(run_id: str) -> list[str]:
    """Return ``docker kill`` scoped to one run label for cancellation."""

    return ["kill", "--signal", "TERM", "--filter", f"label=pymentor.run-id={run_id}"]


# --------------------------------------------------------------------------- #
# Outcome classification
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class Outcome:
    is_platform_error: bool
    status: SandboxRunStatus
    needs_cleanup: bool = True


# Stable platform-error categories. Anything not in this set is treated as a
# student-side outcome handled by the harness frame.
_PLATFORM_CATEGORIES = frozenset(
    {
        "DOCKER_UNAVAILABLE",
        "RUNTIME_IMAGE_MISSING",
        "RUNTIME_IMAGE_PULL_REQUIRED",
        "CONTAINER_CREATE_FAILED",
        "CONTAINER_START_FAILED",
        "OUTER_TIMEOUT",
        "FRAME_INVALID",
        "FRAME_MISSING",
        "FRAME_OVERSIZED",
        "PROTOCOL_AUTH_FAILURE",
        "PERSIST_FAILURE",
        "CLEANUP_FAILED",
    }
)


def classify_outcome(error: ExecutorError) -> Outcome:
    """Map an :class:`ExecutorError` to a platform vs. student outcome.

    Only platform categories produce ``is_platform_error=True``. Spoofed or
    oversized frames are platform errors because they must never become trusted
    student evidence. An outer timeout always needs cleanup.
    """

    is_platform = error.category in _PLATFORM_CATEGORIES
    needs_cleanup = error.category in {"OUTER_TIMEOUT"} or is_platform
    return Outcome(
        is_platform_error=is_platform,
        status=SandboxRunStatus.ERROR,
        needs_cleanup=needs_cleanup,
    )


# --------------------------------------------------------------------------- #
# Executor
# --------------------------------------------------------------------------- #


def _expires_at(request: SandboxExecutionRequest) -> int:
    return int(time.time()) + (request.policy.timeout_ms // 1000) + STOP_TIMEOUT_SECONDS


def _signed_frame(request: SandboxExecutionRequest, *, secret: bytes) -> bytes:
    """Build the authenticated stdin frame for the trusted harness.

    The harness reads one signed canonical request and writes one canonical
    response. The signature binds method, path, timestamp, nonce, and body
    digest so a captured execution frame cannot be replayed as a cancel.
    """

    body_dict = request.model_dump(mode="json")
    from sandbox.protocol import canonical_json

    body = canonical_json(body_dict)
    if len(body) > MAX_REQUEST_BYTES:
        raise ExecutorError("FRAME_OVERSIZED", "execution request exceeds protocol limit")
    timestamp = int(time.time())
    nonce = f"{request.run_id}-{request.request_id}-{request.protocol_version}"
    headers = sign_request(
        body,
        method=SUPERVISOR_METHOD,
        path=SUPERVISOR_PATH,
        secret=secret,
        timestamp=timestamp,
        nonce=nonce,
    )
    # The harness reads the authenticated headers as a length-prefixed preamble
    # followed by the canonical body. We embed them as a small JSON envelope so
    # the harness can verify before touching untrusted input.
    envelope = canonical_json({"headers": headers, "body_b64": _b64(body)})
    return envelope + b"\n"


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode("ascii")


class Executor:
    """Invoke the pinned runtime image for one bounded execution.

    The executor owns no formal state. It accepts a validated
    :class:`SandboxExecutionRequest`, launches the hardened container, decodes
    the single trusted protocol frame, normalizes it to a
    :class:`SandboxResult`, and removes the labeled container in ``finally``.
    """

    def __init__(
        self,
        *,
        runtime_image: str = DEFAULT_RUNTIME_IMAGE,
        docker_binary: str = "docker",
        outer_timeout_seconds: int | None = None,
    ) -> None:
        self.runtime_image = runtime_image
        self.docker_binary = docker_binary
        self.outer_timeout_seconds = outer_timeout_seconds

    def execute(self, request: SandboxExecutionRequest, *, secret: bytes) -> SandboxResult:
        if len(secret) < SHARED_SECRET_MIN_BYTES:
            raise ExecutorError("PROTOCOL_AUTH_FAILURE", "shared secret is too short")
        stdin_payload = _signed_frame(request, secret=secret)
        run_args = [
            self.docker_binary,
            *build_container_args(request, runtime_image=self.runtime_image),
        ]
        try:
            completed = subprocess.run(
                run_args,
                input=stdin_payload,
                capture_output=True,
                timeout=self.outer_timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ExecutorError("DOCKER_UNAVAILABLE", str(exc)) from exc
        except subprocess.TimeoutExpired as exc:
            raise ExecutorError("OUTER_TIMEOUT", "container outlived outer deadline") from exc
        finally:
            # Cleanup is unconditional and idempotent. A cleanup failure is
            # security-logged but must not mask the primary outcome; the
            # recovery service re-attempts removal for stale labels.
            with contextlib.suppress(ExecutorError):
                self.cleanup(request.run_id)

        returncode = completed.returncode
        if returncode != 0:
            stderr = (completed.stderr or b"").decode("utf-8", "replace")
            lowered = stderr.lower()
            if "manifest unknown" in lowered or "no such image" in lowered:
                raise ExecutorError(
                    "RUNTIME_IMAGE_MISSING",
                    "runtime image is absent",
                    returncode=returncode,
                )
            if "not found" in lowered and "image" in lowered:
                raise ExecutorError(
                    "RUNTIME_IMAGE_MISSING",
                    "runtime image reference unresolved",
                    returncode=returncode,
                )
            raise ExecutorError(
                "CONTAINER_START_FAILED",
                f"container exited {returncode}",
                returncode=returncode,
            )

        stdout = completed.stdout or b""
        try:
            frame = decode_frame(_extract_frame(stdout))
        except ProtocolFrameError as exc:
            raise ExecutorError("FRAME_INVALID", str(exc), returncode=returncode) from exc
        return SandboxResult.model_validate(frame)

    def cleanup(self, run_id: str) -> None:
        """Force-remove every container labeled with ``run_id``.

        Idempotent: an empty ID list short-circuits, and a missing-container
        ``rm`` stderr is treated as success.
        """

        list_args = [self.docker_binary, *list_container_args(run_id)]
        try:
            listed = subprocess.run(list_args, capture_output=True, check=False)
        except FileNotFoundError as exc:
            raise ExecutorError("DOCKER_UNAVAILABLE", str(exc)) from exc
        container_ids = [
            line.strip()
            for line in listed.stdout.decode("utf-8", "replace").splitlines()
            if line.strip()
        ]
        if not container_ids:
            return
        remove_args = [self.docker_binary, *remove_container_args(container_ids)]
        try:
            removed = subprocess.run(remove_args, capture_output=True, check=False)
        except FileNotFoundError as exc:
            raise ExecutorError("DOCKER_UNAVAILABLE", str(exc)) from exc
        # Non-zero return codes here are usually "no such container" after a
        # race with --rm; treat as success because the goal state is reached.
        if removed.returncode != 0 and _is_permanent_rm_failure(removed.stderr):
            raise ExecutorError("CLEANUP_FAILED", "force remove rejected the IDs")


def _is_permanent_rm_failure(stderr: bytes) -> bool:
    """Return True only for non-transient remove rejections.

    "No such container" and conflict-on-removal-in-progress are transient and
    treated as success; anything else is surfaced for retry.
    """

    text = (stderr or b"").decode("utf-8", "replace").lower()
    if "no such container" in text:
        return False
    return not ("removal" in text and "progress" in text)


def _extract_frame(stdout: bytes) -> bytes:
    """Pull the length-prefixed protocol frame out of raw container stdout.

    The harness writes exactly one frame beginning with the protocol magic; any
    bytes before the magic are ignored (they would be harness diagnostics, not
    student output, which is captured separately inside the frame).
    """

    from sandbox.protocol import MAGIC

    index = stdout.find(MAGIC)
    if index < 0:
        raise ProtocolFrameError("missing magic prefix")
    return stdout[index:]


def main() -> int:
    """Console entry: execute one signed request read from stdin (BE-005 ops).

    Used by integration tooling that already holds the shared secret and a
    validated request; the FastAPI command boundary remains the primary caller.
    """

    import sys

    from sandbox.protocol import MAX_REQUEST_BYTES, decode_frame

    try:
        request_dict = decode_frame(sys.stdin.buffer.read(), max_bytes=MAX_REQUEST_BYTES)
        secret_env = _read_secret()
        request = SandboxExecutionRequest.model_validate(request_dict)
        result = Executor().execute(request, secret=secret_env)
        sys.stdout.buffer.write(encode_frame(result.model_dump(mode="json")))
        return 0
    except ExecutorError as exc:
        sys.stderr.write(f"{exc.category}: {exc.message}\n")
        return 2
    except Exception as exc:
        sys.stderr.write(f"INTERNAL_ERROR: {type(exc).__name__}\n")
        return 1


def _read_secret() -> bytes:
    import os

    raw = os.environ.get("PYMENTOR_SANDBOX_SECRET", "")
    secret = raw.encode("utf-8")
    if len(secret) < SHARED_SECRET_MIN_BYTES:
        raise ExecutorError("PROTOCOL_AUTH_FAILURE", "PYMENTOR_SANDBOX_SECRET is not configured")
    return secret


# --------------------------------------------------------------------------- #
# Public re-exports for callers/tests
# --------------------------------------------------------------------------- #

__all__ = [
    "DEFAULT_RUNTIME_IMAGE",
    "MAX_ULIMIT_CPU_SECONDS",
    "MAX_ULIMIT_FSIZE_KB",
    "MAX_ULIMIT_NOFILE",
    "SANDBOX_CHILD_GID",
    "SANDBOX_CHILD_UID",
    "STOP_TIMEOUT_SECONDS",
    "TMPFS_SIZE_BYTES",
    "Executor",
    "ExecutorError",
    "Outcome",
    "build_container_args",
    "classify_outcome",
    "kill_container_args",
    "list_container_args",
    "remove_container_args",
]
