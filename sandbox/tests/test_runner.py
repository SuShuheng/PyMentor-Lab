"""Trusted parent/isolated child sandbox runtime behavior."""

from __future__ import annotations

from app.contracts.sandbox import (
    SandboxExecutionRequest,
    SandboxRunStatus,
)
from app.contracts.sandbox import (
    TestVisibility as Visibility,
)
from sandbox.runner import execute_request


def _request(
    source: str,
    *,
    cases: list[dict[str, object]] | None = None,
    entrypoint: dict[str, object] | None = None,
    phase: str = "VISIBLE",
    trace: bool = False,
    output_limit: int = 65_536,
    timeout_ms: int = 2_000,
) -> SandboxExecutionRequest:
    return SandboxExecutionRequest(
        protocol_version="1",
        request_id="req_1",
        run_id="run_0123456789abcdef0123456789abcdef",
        trace_id="trc_1",
        source_code=source,
        entrypoint=entrypoint or {"kind": "FUNCTION", "name": "solve"},
        cases=cases
        or [
            {
                "id": "basic",
                "args": [2],
                "expected": 3,
                "comparison": "EQUAL",
                "transfer": False,
            }
        ],
        allowed_imports=["math", "re"],
        phase=phase,
        policy={
            "timeout_ms": timeout_ms,
            "memory_mb": 128,
            "pids_limit": 32,
            "output_limit_bytes": output_limit,
            "test_limit": 256,
            "trace_frame_limit": 20,
        },
        trace_enabled=trace,
    )


def test_function_cases_and_comparison_modes() -> None:
    result = execute_request(
        _request(
            "def solve(value):\n    return value",
            cases=[
                {"id": "equal", "args": [3], "expected": 3},
                {
                    "id": "approx",
                    "args": [0.1 + 0.2],
                    "expected": 0.3,
                    "comparison": "APPROX",
                },
                {
                    "id": "unordered",
                    "args": [[3, 1, 2]],
                    "expected": [1, 2, 3],
                    "comparison": "UNORDERED",
                },
                {
                    "id": "matches",
                    "args": ["value-42"],
                    "expected": r"value-\d+",
                    "comparison": "MATCHES",
                },
            ],
        )
    )
    assert result.status == SandboxRunStatus.PASSED
    assert [row.passed for row in result.tests] == [True, True, True, True]


def test_hidden_case_uses_safe_display_name() -> None:
    result = execute_request(
        _request(
            "def solve(value):\n    return value + 1",
            phase="HIDDEN",
            cases=[
                {
                    "id": "secret-boundary-id",
                    "args": [1],
                    "expected": 2,
                    "transfer": True,
                }
            ],
        )
    )
    assert result.tests[0].visibility == Visibility.HIDDEN
    assert result.tests[0].display_name == "hidden-1"


def test_script_case_uses_declarative_stdin_and_stdout() -> None:
    result = execute_request(
        _request(
            "name = input()\nprint('hello', name)",
            entrypoint={"kind": "SCRIPT"},
            cases=[
                {
                    "id": "script",
                    "stdin": "Ada\n",
                    "expected_stdout": "hello Ada\n",
                }
            ],
        )
    )
    assert result.status == SandboxRunStatus.PASSED
    assert result.tests[0].stdout == "hello Ada\n"


def test_policy_syntax_and_runtime_errors_are_student_errors_without_traceback() -> None:
    for source, category in [
        ("import os\ndef solve(value):\n    return value", "IMPORT_DENIED"),
        ("def solve(:", "SYNTAX_ERROR"),
        ("def solve(value):\n    return 1 / 0", "RUNTIME_ERROR"),
    ]:
        result = execute_request(_request(source))
        assert result.status == SandboxRunStatus.ERROR
        assert result.platform_error is None
        assert result.user_error is not None and category in result.user_error
        assert "Traceback" not in result.stderr
        assert "Traceback" not in result.user_error


def test_timeout_is_classified_without_platform_error() -> None:
    result = execute_request(
        _request(
            "def solve(value):\n    while True:\n        pass",
            timeout_ms=100,
        )
    )
    assert result.status == SandboxRunStatus.TIMEOUT
    assert result.platform_error is None
    assert result.user_error is not None and "TIMEOUT" in result.user_error


def test_output_and_trace_are_bounded_and_flagged() -> None:
    result = execute_request(
        _request(
            "def solve(value):\n    print('x' * 5000)\n    total = value + 1\n    return total",
            trace=True,
            output_limit=1_024,
        )
    )
    assert result.status == SandboxRunStatus.PASSED
    assert len(result.stdout.encode()) <= 1_024
    assert result.stdout_truncated is True
    assert result.trace_frames is not None
    assert [frame.sequence for frame in result.trace_frames] == list(
        range(1, len(result.trace_frames) + 1)
    )
    assert all(
        list((frame.locals or {}).keys()) == sorted((frame.locals or {}).keys())
        for frame in result.trace_frames
    )


def test_failed_assertion_is_a_bounded_failed_result() -> None:
    result = execute_request(
        _request(
            "def solve(value):\n    return value",
            cases=[{"id": "wrong", "args": [1], "expected": 2}],
        )
    )
    assert result.status == SandboxRunStatus.FAILED
    assert result.passed is False
    assert result.tests[0].passed is False
    assert result.tests[0].message == "result did not match expected value"
