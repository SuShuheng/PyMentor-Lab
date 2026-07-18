"""BE-005 private task-policy validation and student projection."""

from __future__ import annotations

import pytest

from app.task_policy import InvalidTaskPolicy, parse_task_policy, public_task_snapshot


def _snapshot() -> dict[str, object]:
    return {
        "prompt": "Return the sum.",
        "tests_policy": {
            "entrypoint": {"kind": "FUNCTION", "name": "solve"},
            "allowed_imports": ["math"],
            "visible": [
                {
                    "id": "visible-basic",
                    "args": [[1, 2]],
                    "kwargs": {},
                    "expected": 3,
                    "comparison": "EQUAL",
                    "transfer": False,
                }
            ],
            "hidden": [
                {
                    "id": "hidden-boundary",
                    "args": [[0, 0]],
                    "kwargs": {},
                    "expected": 0,
                    "comparison": "EQUAL",
                    "transfer": True,
                }
            ],
        },
        "hint_policy": {
            "max_level": 1,
            "hints": [
                {
                    "key": "inspect-bound",
                    "level": 1,
                    "content": "Check the stop value.",
                    "independence_cost": 10,
                }
            ],
        },
        "mastery_policy": {"independence_min": 0.7},
        "resource_versions": {},
        "scenario_key": "sum-v1",
    }


def test_public_task_snapshot_removes_hidden_cases_and_hint_content() -> None:
    public = public_task_snapshot(_snapshot())

    tests_policy = public["tests_policy"]
    assert isinstance(tests_policy, dict)
    assert "hidden" not in tests_policy
    assert tests_policy["visible"][0]["id"] == "visible-basic"
    assert public["hint_policy"] == {"max_level": 1}
    assert "hidden-boundary" not in str(public)
    assert "Check the stop value." not in str(public)


def test_task_policy_rejects_import_outside_global_allowlist() -> None:
    snapshot = _snapshot()
    tests_policy = snapshot["tests_policy"]
    assert isinstance(tests_policy, dict)
    tests_policy["allowed_imports"] = ["os"]

    with pytest.raises(InvalidTaskPolicy, match="non-allowlisted import"):
        parse_task_policy(snapshot)


def test_task_policy_rejects_more_than_256_cases() -> None:
    snapshot = _snapshot()
    tests_policy = snapshot["tests_policy"]
    assert isinstance(tests_policy, dict)
    visible = tests_policy["visible"]
    assert isinstance(visible, list)
    tests_policy["visible"] = visible * 257
    tests_policy["hidden"] = []

    with pytest.raises(InvalidTaskPolicy, match="more than 256 cases"):
        parse_task_policy(snapshot)


def test_task_policy_rejects_missing_hint_level() -> None:
    snapshot = _snapshot()
    hint_policy = snapshot["hint_policy"]
    assert isinstance(hint_policy, dict)
    hint_policy["max_level"] = 2

    with pytest.raises(InvalidTaskPolicy, match="one ordered hint per level"):
        parse_task_policy(snapshot)
