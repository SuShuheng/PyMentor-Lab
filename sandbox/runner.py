"""Sandbox runner skeleton.

The real isolated execution (no network, bounded CPU/memory/process/file/output/
time, allowlisted imports, platform-error separation) lands in BE-005. At the
bootstrap stage this module only proves the sandbox consumes the shared
``SandboxResult`` contract and returns a bounded result whose user/platform
error fields are correctly separated.
"""

from __future__ import annotations

import uuid

from app.contracts.sandbox import SandboxResourceUsage, SandboxResult, SandboxRunStatus


def stub_result() -> SandboxResult:
    """Return a fixed, contract-shaped SandboxResult for bootstrap wiring.

    BE-005 replaces this with a real subprocess-isolated runner. The shape is
    what matters here: platform failures (``platform_error``) never reduce
    mastery, and student failures (``user_error``) are safe to record.
    """

    return SandboxResult(
        run_id=f"run_{uuid.uuid4().hex}",
        status=SandboxRunStatus.PASSED,
        passed=True,
        stdout="",
        stderr="",
        tests=[],
        trace_frames=None,
        resource_usage=SandboxResourceUsage(
            cpu_ms=0,
            wall_ms=0,
            peak_memory_kb=None,
            exit_code=0,
        ),
        stdout_truncated=False,
        stderr_truncated=False,
        trace_truncated=False,
        user_error=None,
        platform_error=None,
    )
