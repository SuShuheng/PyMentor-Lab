"""Deny-first AST validation for untrusted student Python."""

from __future__ import annotations

import ast

MAX_SOURCE_BYTES = 65_536
MAX_AST_NODES = 2_000
MAX_AST_DEPTH = 80
RESERVED_PREFIX = "_pymentor_"

DENIED_CALLS = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "delattr",
        "dir",
        "eval",
        "exec",
        "exit",
        "getattr",
        "globals",
        "help",
        "locals",
        "open",
        "quit",
        "setattr",
        "vars",
    }
)


class StudentPolicyError(ValueError):
    def __init__(self, category: str, message: str) -> None:
        self.category = category
        self.message = message
        super().__init__(f"{category}: {message}")


class StudentSyntaxError(ValueError):
    def __init__(self, *, line: int, message: str) -> None:
        self.line = line
        self.message = message
        super().__init__(f"SYNTAX_ERROR line {line}: {message}")


def _binding_allowed(name: str) -> bool:
    return not name.startswith(RESERVED_PREFIX) and not name.startswith("__")


def _check_budget(tree: ast.AST) -> None:
    count = 0
    stack: list[tuple[ast.AST, int]] = [(tree, 0)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > MAX_AST_NODES or depth > MAX_AST_DEPTH:
            raise StudentPolicyError("AST_BUDGET", "source AST exceeds safe budget")
        stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))


class PolicyVisitor(ast.NodeVisitor):
    def __init__(self, allowed_imports: frozenset[str]) -> None:
        self.allowed_imports = allowed_imports

    def _check_binding(self, name: str) -> None:
        if not _binding_allowed(name):
            raise StudentPolicyError("RESERVED_NAME", f"reserved name {name!r}")

    def _check_module(self, name: str) -> None:
        root = name.split(".", 1)[0]
        if root not in self.allowed_imports:
            raise StudentPolicyError("IMPORT_DENIED", f"import {root!r} is denied")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_module(alias.name)
            self._check_binding(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level != 0 or node.module is None:
            raise StudentPolicyError("IMPORT_DENIED", "relative import is denied")
        self._check_module(node.module)
        for alias in node.names:
            if alias.name == "*":
                raise StudentPolicyError("IMPORT_DENIED", "star import is denied")
            self._check_binding(alias.asname or alias.name)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in DENIED_CALLS:
            raise StudentPolicyError("CALL_DENIED", f"call {node.func.id!r} is denied")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if not _binding_allowed(node.id):
            raise StudentPolicyError("RESERVED_NAME", f"reserved name {node.id!r}")

    def visit_arg(self, node: ast.arg) -> None:
        self._check_binding(node.arg)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_binding(node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_binding(node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._check_binding(node.name)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        for name in node.names:
            self._check_binding(name)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        for name in node.names:
            self._check_binding(name)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            node.attr.startswith("__")
            or node.attr.endswith("__")
            or node.attr.startswith(RESERVED_PREFIX)
        ):
            raise StudentPolicyError("ATTRIBUTE_DENIED", f"attribute {node.attr!r} is denied")
        self.generic_visit(node)


def validate_source(source: str, *, allowed_imports: frozenset[str]) -> ast.Module:
    if not 1 <= len(source.encode("utf-8")) <= MAX_SOURCE_BYTES:
        raise StudentPolicyError("SOURCE_SIZE", "source must contain 1..65536 bytes")
    try:
        tree = ast.parse(source, mode="exec", type_comments=True)
    except SyntaxError as exc:
        raise StudentSyntaxError(line=exc.lineno or 1, message=exc.msg) from None
    _check_budget(tree)
    PolicyVisitor(allowed_imports).visit(tree)
    return tree
