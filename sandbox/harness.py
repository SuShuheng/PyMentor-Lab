"""Standard-library trusted parent and isolated per-case child harness."""

from __future__ import annotations

import ast
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sandbox.policy import StudentPolicyError, StudentSyntaxError, validate_source
from sandbox.protocol import MAX_REQUEST_BYTES, decode_frame, encode_frame
from sandbox.tracing import instrument_source

MAX_STREAM_BYTES = 32_768
RUNTIME_ALLOWED_IMPORTS = frozenset(
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

_CHILD_PROGRAM = r"""
import builtins
import contextlib
import io
import json
import math
import re
import sys

payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
with open("student.py", "r", encoding="utf-8") as source_file:
    source = source_file.read()

class Writer(io.TextIOBase):
    def __init__(self, limit):
        self.limit = limit
        self.parts = []
        self.size = 0
        self.truncated = False
    def write(self, value):
        text = str(value)
        encoded = text.encode("utf-8", "replace")
        room = max(0, self.limit - self.size)
        kept = encoded[:room]
        while kept:
            try:
                decoded = kept.decode("utf-8")
                break
            except UnicodeDecodeError:
                kept = kept[:-1]
        else:
            decoded = ""
        if decoded:
            self.parts.append(decoded)
            self.size += len(kept)
        if len(encoded) > room:
            self.truncated = True
        return len(text)
    def getvalue(self):
        return "".join(self.parts)

def safe(value, depth=0, seen=None):
    if seen is None:
        seen = set()
    if depth > 4:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, str)):
        return value[:512] if isinstance(value, str) else value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    identity = id(value)
    if identity in seen:
        return "<cycle>"
    if isinstance(value, (list, tuple)):
        seen.add(identity)
        result = [safe(item, depth + 1, seen) for item in value[:32]]
        if len(value) > 32:
            result.append("<truncated>")
        seen.remove(identity)
        return result
    if isinstance(value, dict):
        seen.add(identity)
        pairs = sorted(
            ((str(key)[:128], item) for key, item in value.items()),
            key=lambda item: item[0],
        )
        result = {key: safe(item, depth + 1, seen) for key, item in pairs[:32]}
        if len(pairs) > 32:
            result["<truncated>"] = len(pairs) - 32
        seen.remove(identity)
        return result
    return "<" + type(value).__name__ + ">"

allowed_imports = frozenset(payload["allowed_imports"])
real_import = builtins.__import__
def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".", 1)[0]
    if level != 0 or root not in allowed_imports:
        raise ImportError("import denied")
    return real_import(name, globals, locals, fromlist, level)

allowed_builtin_names = (
    "ArithmeticError", "AssertionError", "BaseException", "EOFError", "Exception",
    "IndexError", "KeyError", "RuntimeError", "StopIteration", "TypeError", "ValueError",
    "ZeroDivisionError", "abs", "all", "any", "bool", "chr", "dict", "divmod",
    "enumerate", "filter", "float", "format", "frozenset", "hash", "hex", "int",
    "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min", "next",
    "object", "oct", "ord", "pow", "print", "property", "range", "repr", "reversed",
    "round", "set", "slice", "sorted", "str", "sum", "super", "tuple", "type", "zip",
    "__build_class__",
)
safe_builtins = {name: getattr(builtins, name) for name in allowed_builtin_names}
safe_builtins["__import__"] = safe_import

stdin_lines = iter(payload.get("stdin", "").splitlines())
def safe_input(prompt=""):
    if prompt:
        print(prompt, end="")
    try:
        return next(stdin_lines)
    except StopIteration:
        raise EOFError("input exhausted") from None
safe_builtins["input"] = safe_input

stdout = Writer(payload["output_limit"])
stderr = Writer(payload["output_limit"])
frames = []
trace_truncated = False
def trusted_trace(event, line):
    global trace_truncated
    if not payload["trace_enabled"]:
        return
    if len(frames) >= payload["trace_limit"]:
        trace_truncated = True
        return
    frame = sys._getframe(1)
    rendered = {}
    for key in sorted(frame.f_locals):
        if key.startswith("_"):
            continue
        rendered_value = json.dumps(
            safe(frame.f_locals[key]),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        rendered[key[:128]] = rendered_value[:512]
        if len(rendered) >= 32:
            break
    frames.append(
        {
            "line": int(line),
            "event": event,
            "func_name": frame.f_code.co_name[:256],
            "locals": rendered,
        }
    )

namespace = {
    "__builtins__": safe_builtins,
    "__name__": "__student__",
    "_pymentor_trace": trusted_trace,
}
response = None
try:
    code = compile(source, "<student>", "exec")
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exec(code, namespace, namespace)
        if payload["entrypoint"]["kind"] == "FUNCTION":
            name = payload["entrypoint"].get("name")
            function = namespace.get(name)
            if not callable(function):
                raise TypeError("function entrypoint not found")
            actual = function(*payload.get("args", []), **payload.get("kwargs", {}))
        else:
            actual = None
    response = {
        "ok": True,
        "actual": safe(actual),
        "stdout": stdout.getvalue(),
        "stderr": stderr.getvalue(),
        "stdout_truncated": stdout.truncated,
        "stderr_truncated": stderr.truncated,
        "trace_frames": frames,
        "trace_truncated": trace_truncated,
    }
except BaseException as exc:
    message = str(exc).replace("\r", " ").replace("\n", " ")[:1000]
    response = {
        "ok": False,
        "category": "RUNTIME_ERROR",
        "message": type(exc).__name__ + (": " + message if message else ""),
        "stdout": stdout.getvalue(),
        "stderr": stderr.getvalue(),
        "stdout_truncated": stdout.truncated,
        "stderr_truncated": stderr.truncated,
        "trace_frames": frames,
        "trace_truncated": trace_truncated,
    }
sys.stdout.write(
    json.dumps(
        response,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
)
"""


class HarnessRequestError(ValueError):
    pass


def _platform_failure(run_id: str, category: str, message: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": "ERROR",
        "passed": False,
        "stdout": "",
        "stderr": "",
        "tests": [],
        "trace_frames": None,
        "resource_usage": {
            "cpu_ms": 0,
            "wall_ms": 0,
            "peak_memory_kb": None,
            "exit_code": None,
        },
        "stdout_truncated": False,
        "stderr_truncated": False,
        "trace_truncated": False,
        "user_error": None,
        "platform_error": f"{category}: {message}",
    }


def _student_failure(
    run_id: str, category: str, message: str, *, status: str = "ERROR"
) -> dict[str, Any]:
    result = _platform_failure(run_id, category, message)
    result["status"] = status
    result["user_error"] = f"{category}: {message}"
    result["platform_error"] = None
    return result


def _request_fields(request: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    try:
        run_id = request["run_id"]
        source = request["source_code"]
        policy = request["policy"]
    except KeyError as exc:
        raise HarnessRequestError("execution request is incomplete") from exc
    if not isinstance(run_id, str) or not isinstance(source, str) or not isinstance(policy, dict):
        raise HarnessRequestError("execution request field types are invalid")
    return run_id, source, policy


def _limit_preexec(memory_mb: int, timeout_ms: int, pids_limit: int) -> Callable[[], None] | None:
    if os.name != "posix":
        return None

    def apply_limits() -> None:
        import resource

        cpu_seconds = max(1, math.ceil(timeout_ms / 1000))
        memory_bytes = memory_mb * 1024 * 1024
        resource.setrlimit(  # type: ignore[attr-defined]
            resource.RLIMIT_CPU,  # type: ignore[attr-defined]
            (cpu_seconds, cpu_seconds + 1),
        )
        resource.setrlimit(  # type: ignore[attr-defined]
            resource.RLIMIT_AS,  # type: ignore[attr-defined]
            (memory_bytes, memory_bytes),
        )
        resource.setrlimit(  # type: ignore[attr-defined]
            resource.RLIMIT_FSIZE,  # type: ignore[attr-defined]
            (1_048_576, 1_048_576),
        )
        resource.setrlimit(  # type: ignore[attr-defined]
            resource.RLIMIT_NOFILE,  # type: ignore[attr-defined]
            (64, 64),
        )
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(  # type: ignore[attr-defined]
                resource.RLIMIT_NPROC,
                (pids_limit, pids_limit),
            )

    return apply_limits


def _compare(actual: Any, expected: Any, comparison: str) -> bool:
    if comparison == "EQUAL":
        return bool(actual == expected)
    if comparison == "APPROX":
        return (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and isinstance(expected, (int, float))
            and not isinstance(expected, bool)
            and math.isclose(float(actual), float(expected), rel_tol=1e-9, abs_tol=1e-9)
        )
    if comparison == "UNORDERED":
        if not isinstance(actual, list) or not isinstance(expected, list):
            return False

        def canonical(value: Any) -> str:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

        return sorted(map(canonical, actual)) == sorted(map(canonical, expected))
    if comparison == "MATCHES":
        return (
            isinstance(actual, str)
            and isinstance(expected, str)
            and re.fullmatch(expected, actual) is not None
        )
    return False


def _bounded_join(current: str, addition: str, limit: int) -> tuple[str, bool]:
    current_bytes = current.encode("utf-8")
    addition_bytes = addition.encode("utf-8")
    room = max(0, limit - len(current_bytes))
    kept = addition_bytes[:room]
    while kept:
        try:
            suffix = kept.decode("utf-8")
            break
        except UnicodeDecodeError:
            kept = kept[:-1]
    else:
        suffix = ""
    return current + suffix, len(addition_bytes) > room


def execute_request(request: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        run_id, source, policy = _request_fields(request)
        allowed_imports = frozenset(request.get("allowed_imports", []))
        if not allowed_imports <= RUNTIME_ALLOWED_IMPORTS:
            raise HarnessRequestError("request contains non-allowlisted imports")
        validate_source(source, allowed_imports=allowed_imports)
        if request.get("trace_enabled", False):
            tree = instrument_source(source, allowed_imports=allowed_imports)
            executable_source = ast.unparse(tree)
        else:
            executable_source = source
    except StudentSyntaxError as exc:
        return _student_failure(
            str(request.get("run_id", "invalid")),
            "SYNTAX_ERROR",
            f"line {exc.line}: {exc.message}",
        )
    except StudentPolicyError as exc:
        return _student_failure(str(request.get("run_id", "invalid")), exc.category, exc.message)
    except Exception as exc:
        return _platform_failure(
            str(request.get("run_id", "invalid")),
            "INVALID_REQUEST",
            str(exc)[:1000],
        )

    tests: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    stdout = ""
    stderr = ""
    stdout_truncated = False
    stderr_truncated = False
    trace_truncated = False
    status = "PASSED"
    user_error: str | None = None
    last_exit_code: int | None = 0
    output_limit = min(int(policy["output_limit_bytes"]), MAX_STREAM_BYTES)
    trace_limit = int(policy["trace_frame_limit"])
    timeout_seconds = int(policy["timeout_ms"]) / 1000
    visibility = str(request.get("phase", "VISIBLE"))

    try:
        with tempfile.TemporaryDirectory(prefix="pymentor-sandbox-") as temp_dir:
            source_path = Path(temp_dir) / "student.py"
            source_path.write_text(executable_source, encoding="utf-8")
            for ordinal, case in enumerate(request.get("cases", []), start=1):
                child_payload = {
                    "entrypoint": request["entrypoint"],
                    "args": case.get("args", []),
                    "kwargs": case.get("kwargs", {}),
                    "stdin": case.get("stdin") or "",
                    "allowed_imports": sorted(allowed_imports),
                    "trace_enabled": bool(request.get("trace_enabled", False)),
                    "trace_limit": max(0, trace_limit - len(frames)),
                    "output_limit": output_limit,
                }
                try:
                    completed = subprocess.run(
                        [sys.executable, "-I", "-S", "-X", "utf8", "-c", _CHILD_PROGRAM],
                        input=json.dumps(
                            child_payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode("utf-8"),
                        capture_output=True,
                        cwd=temp_dir,
                        env={},
                        timeout=timeout_seconds,
                        check=False,
                        preexec_fn=_limit_preexec(
                            int(policy["memory_mb"]),
                            int(policy["timeout_ms"]),
                            int(policy["pids_limit"]),
                        ),
                    )
                except subprocess.TimeoutExpired:
                    status = "TIMEOUT"
                    user_error = "TIMEOUT: execution exceeded wall-clock limit"
                    tests.append(
                        {
                            "case_id": str(case["id"]),
                            "display_name": str(case["id"])
                            if visibility == "VISIBLE"
                            else f"hidden-{ordinal}",
                            "visibility": visibility,
                            "comparison": str(case.get("comparison", "EQUAL")),
                            "transfer": bool(case.get("transfer", False)),
                            "passed": False,
                            "message": "execution timed out",
                            "stdout": "",
                            "stderr": "",
                            "stdout_truncated": False,
                            "stderr_truncated": False,
                            "duration_ms": int(timeout_seconds * 1000),
                        }
                    )
                    last_exit_code = None
                    break

                last_exit_code = completed.returncode
                if len(completed.stdout) > 256 * 1024:
                    raise HarnessRequestError("child control response too large")
                try:
                    child = json.loads(completed.stdout.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    detail = completed.stderr.decode("utf-8", "replace")[:500]
                    raise HarnessRequestError(
                        f"child emitted invalid control response: {detail}"
                    ) from exc
                if not isinstance(child, dict):
                    raise HarnessRequestError("child control response must be an object")

                case_stdout = str(child.get("stdout", ""))
                case_stderr = str(child.get("stderr", ""))
                stdout, global_stdout_cut = _bounded_join(stdout, case_stdout, output_limit)
                stderr, global_stderr_cut = _bounded_join(stderr, case_stderr, output_limit)
                stdout_truncated = (
                    stdout_truncated or bool(child.get("stdout_truncated")) or global_stdout_cut
                )
                stderr_truncated = (
                    stderr_truncated or bool(child.get("stderr_truncated")) or global_stderr_cut
                )
                for raw_frame in child.get("trace_frames", []):
                    if len(frames) >= trace_limit:
                        trace_truncated = True
                        break
                    frames.append(
                        {
                            "sequence": len(frames) + 1,
                            "line": int(raw_frame["line"]),
                            "event": str(raw_frame["event"]),
                            "func_name": str(raw_frame["func_name"]),
                            "locals": raw_frame.get("locals"),
                        }
                    )
                trace_truncated = trace_truncated or bool(child.get("trace_truncated"))

                comparison = str(case.get("comparison", "EQUAL"))
                expected = (
                    case.get("expected_stdout")
                    if request["entrypoint"]["kind"] == "SCRIPT"
                    else case.get("expected")
                )
                actual = (
                    case_stdout
                    if request["entrypoint"]["kind"] == "SCRIPT"
                    else child.get("actual")
                )
                child_ok = bool(child.get("ok"))
                passed = child_ok and _compare(actual, expected, comparison)
                message = None
                if not child_ok:
                    status = "ERROR"
                    category = str(child.get("category", "RUNTIME_ERROR"))
                    safe_message = str(child.get("message", "runtime error"))[:1000]
                    user_error = f"{category}: {safe_message}"
                    message = safe_message
                elif not passed:
                    status = "FAILED"
                    message = "result did not match expected value"
                tests.append(
                    {
                        "case_id": str(case["id"]),
                        "display_name": str(case["id"])
                        if visibility == "VISIBLE"
                        else f"hidden-{ordinal}",
                        "visibility": visibility,
                        "comparison": comparison,
                        "transfer": bool(case.get("transfer", False)),
                        "passed": passed,
                        "message": message,
                        "stdout": case_stdout,
                        "stderr": case_stderr,
                        "stdout_truncated": bool(child.get("stdout_truncated")),
                        "stderr_truncated": bool(child.get("stderr_truncated")),
                        "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
                    }
                )
                if not child_ok:
                    break
    except Exception as exc:
        return _platform_failure(run_id, "HARNESS_ERROR", str(exc)[:1000])

    wall_ms = max(0, int((time.monotonic() - started) * 1000))
    return {
        "run_id": run_id,
        "status": status,
        "passed": status == "PASSED" and bool(tests) and all(row["passed"] for row in tests),
        "stdout": stdout,
        "stderr": stderr,
        "tests": tests,
        "trace_frames": frames if request.get("trace_enabled", False) else None,
        "resource_usage": {
            "cpu_ms": 0,
            "wall_ms": wall_ms,
            "peak_memory_kb": None,
            "exit_code": last_exit_code,
        },
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "trace_truncated": trace_truncated,
        "user_error": user_error,
        "platform_error": None,
    }


def main() -> int:
    try:
        request = decode_frame(sys.stdin.buffer.read(), max_bytes=MAX_REQUEST_BYTES)
        result = execute_request(request)
        sys.stdout.buffer.write(encode_frame(result))
        return 0
    except Exception as exc:
        failure = _platform_failure("invalid", "HARNESS_ERROR", str(exc)[:1000])
        sys.stdout.buffer.write(encode_frame(failure))
        return 1


if __name__ == "__main__":  # pragma: no cover - exercised by runtime image
    raise SystemExit(main())
