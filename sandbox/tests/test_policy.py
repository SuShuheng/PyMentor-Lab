"""Deny-first AST policy for untrusted student Python."""

from __future__ import annotations

import pytest

from sandbox.policy import StudentPolicyError, StudentSyntaxError, validate_source


@pytest.mark.parametrize(
    "source, category",
    [
        ("import os", "IMPORT_DENIED"),
        ("from subprocess import run", "IMPORT_DENIED"),
        ("from math import *", "IMPORT_DENIED"),
        ("from .math import sqrt", "IMPORT_DENIED"),
        ("__import__('socket')", "CALL_DENIED"),
        ("compile('1+1', '<x>', 'eval')", "CALL_DENIED"),
        ("open('../../secret')", "CALL_DENIED"),
        ("globals()['_pymentor_trace'] = None", "CALL_DENIED"),
        ("getattr(object, '__subclasses__')", "CALL_DENIED"),
        ("object.__subclasses__()", "ATTRIBUTE_DENIED"),
        ("_pymentor_trace = lambda: None", "RESERVED_NAME"),
        ("def solve(_pymentor_value):\n    return 1", "RESERVED_NAME"),
    ],
)
def test_policy_rejects_dangerous_source(source: str, category: str) -> None:
    with pytest.raises(StudentPolicyError) as caught:
        validate_source(source, allowed_imports=frozenset({"math"}))
    assert caught.value.category == category


def test_policy_allows_named_allowlisted_import_and_normal_code() -> None:
    tree = validate_source(
        "from math import sqrt\ndef solve(value):\n    return sqrt(value)",
        allowed_imports=frozenset({"math"}),
    )
    assert len(tree.body) == 2


def test_policy_reports_syntax_and_source_byte_bounds() -> None:
    with pytest.raises(StudentSyntaxError) as syntax:
        validate_source("def broken(:", allowed_imports=frozenset())
    assert syntax.value.line == 1
    with pytest.raises(StudentPolicyError) as oversized:
        validate_source("界" * 22_000, allowed_imports=frozenset())
    assert oversized.value.category == "SOURCE_SIZE"


def test_policy_enforces_ast_node_and_depth_budgets() -> None:
    source = "value = 1\n" * 2_100
    with pytest.raises(StudentPolicyError) as caught:
        validate_source(source, allowed_imports=frozenset())
    assert caught.value.category == "AST_BUDGET"
