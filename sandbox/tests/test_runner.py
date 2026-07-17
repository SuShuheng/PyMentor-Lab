"""Tests for the sandbox runner skeleton (bounded result contract)."""

from __future__ import annotations

from app.contracts.sandbox import SandboxResult, SandboxRunStatus
from sandbox.runner import stub_result


def test_stub_result_is_bounded_contract_shape() -> None:
    """The stub returns a valid SandboxResult that downstream policy can consume."""
    result = stub_result()
    assert isinstance(result, SandboxResult)
    assert result.status == SandboxRunStatus.PASSED
    assert result.passed is True
    assert result.run_id.startswith("run_")
    assert result.resource_usage.exit_code == 0
    assert result.stdout_truncated is False


def test_user_and_platform_error_are_separated() -> None:
    """Both error fields exist and default to None (separation is structural).

    The contract requires platform failures to never reduce mastery, so the two
    error kinds MUST be distinct fields. This test guards against accidentally
    merging them.
    """
    result = stub_result()
    assert hasattr(result, "user_error")
    assert hasattr(result, "platform_error")
    assert result.user_error is None
    assert result.platform_error is None
