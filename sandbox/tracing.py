"""Deterministic statement tracing and bounded value sanitation."""

from __future__ import annotations

import ast
import math
import re
from typing import Any, cast

_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 1:
        return value[:limit]
    return value[: limit - 1] + "…"


def sanitize_value(
    value: object,
    *,
    max_depth: int = 4,
    max_items: int = 32,
    max_key_chars: int = 128,
    max_value_chars: int = 512,
) -> Any:
    """Return a deterministic JSON-safe value without raw addresses or cycles."""

    seen: set[int] = set()

    def visit(item: object, depth: int) -> Any:
        if depth > max_depth:
            return "<max-depth>"
        if item is None or isinstance(item, (bool, int)):
            return item
        if isinstance(item, float):
            return item if math.isfinite(item) else repr(item)
        if isinstance(item, str):
            return _clip(item, max_value_chars)

        identity = id(item)
        if identity in seen:
            return "<cycle>"
        if isinstance(item, (list, tuple)):
            seen.add(identity)
            rendered_list = [visit(child, depth + 1) for child in item[:max_items]]
            if len(item) > max_items:
                rendered_list.append("<truncated>")
            seen.remove(identity)
            return rendered_list
        if isinstance(item, dict):
            seen.add(identity)
            pairs = sorted(
                ((_clip(str(key), max_key_chars), child) for key, child in item.items()),
                key=lambda pair: pair[0],
            )
            rendered_dict = {key: visit(child, depth + 1) for key, child in pairs[:max_items]}
            if len(pairs) > max_items:
                rendered_dict["<truncated>"] = f"{len(pairs) - max_items} item(s)"
            seen.remove(identity)
            return rendered_dict

        try:
            rendered_repr = repr(item)
        except Exception:
            rendered_repr = f"<{type(item).__name__}>"
        return _clip(_ADDRESS.sub("0x…", rendered_repr), max_value_chars)

    return visit(value, 0)


class TraceTransformer(ast.NodeTransformer):
    """Insert a trusted callback immediately before every statement."""

    def generic_visit(self, node: ast.AST) -> ast.AST:
        transformed = super().generic_visit(node)
        for field, value in ast.iter_fields(transformed):
            if not isinstance(value, list) or not any(isinstance(item, ast.stmt) for item in value):
                continue
            statements: list[ast.stmt] = []
            for item in value:
                if not isinstance(item, ast.stmt):
                    continue
                callback = ast.Expr(
                    value=ast.Call(
                        func=ast.Name(id="_pymentor_trace", ctx=ast.Load()),
                        args=[
                            ast.Constant(value="line"),
                            ast.Constant(value=item.lineno),
                        ],
                        keywords=[],
                    )
                )
                statements.extend([ast.copy_location(callback, item), item])
            setattr(transformed, field, statements)
        return transformed


def instrument_source(source: str, *, allowed_imports: frozenset[str]) -> ast.Module:
    tree = validate_and_copy(source, allowed_imports=allowed_imports)
    transformed = TraceTransformer().visit(tree)
    ast.fix_missing_locations(transformed)
    return cast(ast.Module, transformed)


def validate_and_copy(source: str, *, allowed_imports: frozenset[str]) -> ast.Module:
    # Local import keeps the policy module independently usable in the tiny runtime.
    from sandbox.policy import validate_source

    return validate_source(source, allowed_imports=allowed_imports)
