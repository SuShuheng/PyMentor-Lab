"""Validation and student-safe projection for versioned task policies."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.contracts.sandbox import (
    SandboxEntrypointKind,
    SandboxHintPolicy,
    SandboxTaskTests,
)

ALLOWED_IMPORTS = frozenset(
    {
        "bisect",
        "collections",
        "decimal",
        "fractions",
        "functools",
        "heapq",
        "itertools",
        "math",
        "operator",
        "random",
        "re",
        "statistics",
        "string",
    }
)


class InvalidTaskPolicy(ValueError):
    """A published task policy cannot be safely executed."""


@dataclass(frozen=True, slots=True)
class CompiledTaskPolicy:
    tests: SandboxTaskTests
    hints: SandboxHintPolicy


def _raw_case_count(raw: object) -> int:
    if not isinstance(raw, dict):
        return 0
    visible = raw.get("visible", [])
    hidden = raw.get("hidden", [])
    if not isinstance(visible, list) or not isinstance(hidden, list):
        return 0
    return len(visible) + len(hidden)


def parse_task_policy(snapshot: dict[str, Any]) -> CompiledTaskPolicy:
    """Parse a trusted snapshot and enforce global execution invariants."""

    raw_tests = snapshot.get("tests_policy")
    raw_hints = snapshot.get("hint_policy")
    if _raw_case_count(raw_tests) > 256:
        raise InvalidTaskPolicy("task policy contains more than 256 cases")

    try:
        tests = SandboxTaskTests.model_validate(raw_tests)
        hints = SandboxHintPolicy.model_validate(raw_hints)
    except ValidationError as exc:
        raise InvalidTaskPolicy(f"invalid task policy: {exc}") from exc

    unexpected_imports = sorted(set(tests.allowed_imports) - ALLOWED_IMPORTS)
    if unexpected_imports:
        raise InvalidTaskPolicy(
            "task policy requests non-allowlisted import(s): " + ", ".join(unexpected_imports)
        )

    if tests.entrypoint.kind == SandboxEntrypointKind.FUNCTION:
        name = tests.entrypoint.name
        if name is None or not name.isidentifier() or name.startswith("__"):
            raise InvalidTaskPolicy("function entrypoint must be a safe identifier")
    elif tests.entrypoint.name is not None:
        raise InvalidTaskPolicy("script entrypoint must not define a function name")

    cases = [*tests.visible, *tests.hidden]
    case_ids = [case.id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise InvalidTaskPolicy("task policy case ids must be unique")

    levels = [hint.level for hint in hints.hints]
    expected_levels = list(range(1, hints.max_level + 1))
    if levels != expected_levels:
        raise InvalidTaskPolicy("hint policy must contain one ordered hint per level")
    keys = [hint.key for hint in hints.hints]
    if len(keys) != len(set(keys)):
        raise InvalidTaskPolicy("hint policy keys must be unique")

    return CompiledTaskPolicy(tests=tests, hints=hints)


def public_task_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a deep, student-safe copy with hidden tests/hint content removed."""

    policy = parse_task_policy(snapshot)
    public = deepcopy(snapshot)
    public["tests_policy"] = {
        "entrypoint": policy.tests.entrypoint.model_dump(mode="json"),
        "allowed_imports": list(policy.tests.allowed_imports),
        "visible": [case.model_dump(mode="json") for case in policy.tests.visible],
    }
    public["hint_policy"] = {"max_level": policy.hints.max_level}
    return public
