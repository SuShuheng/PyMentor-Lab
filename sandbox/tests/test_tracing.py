"""Deterministic trace instrumentation and safe value rendering."""

from __future__ import annotations

from sandbox.tracing import instrument_source, sanitize_value


def test_sanitize_value_sorts_keys_removes_addresses_and_marks_cycles() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)

    class Example:
        pass

    sanitized = sanitize_value({"z": Example(), "a": cyclic, "m": {"b": 2, "a": 1}})
    assert list(sanitized) == ["a", "m", "z"]
    assert sanitized["a"] == ["<cycle>"]
    assert list(sanitized["m"]) == ["a", "b"]
    assert "0x" not in sanitized["z"] or "0x…" in sanitized["z"]


def test_sanitize_value_enforces_depth_item_and_rendered_value_bounds() -> None:
    value = {str(index): "x" * 1_000 for index in range(40)}
    sanitized = sanitize_value(value, max_items=3, max_value_chars=20)
    assert list(sanitized) == ["0", "1", "10", "<truncated>"]
    assert len(sanitized["0"]) <= 20
    deep = sanitize_value([[[[[1]]]]], max_depth=2)
    assert deep == [[["<max-depth>"]]]


def test_instrument_source_emits_deterministic_statement_lines() -> None:
    tree = instrument_source(
        "def solve(value):\n    total = value + 1\n    return total\nresult = solve(2)",
        allowed_imports=frozenset(),
    )
    frames: list[tuple[str, int]] = []

    def trace(event: str, line: int) -> None:
        frames.append((event, line))

    namespace = {"_pymentor_trace": trace}
    exec(compile(tree, "<student>", "exec"), namespace)
    assert frames == [
        ("line", 1),
        ("line", 4),
        ("line", 2),
        ("line", 3),
    ]
