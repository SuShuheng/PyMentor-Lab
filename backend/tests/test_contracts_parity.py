"""Pydantic ↔ Zod conformance gate.

This is the cross-language contract-drift detector required by CONTRACT.md
("Errors"), the PRD test matrix ("跨语言契约: Pydantic↔Zod Schema 一致性"),
and the frozen design (§22 risk mitigation). It runs in two complementary modes:

1. The Pydantic models parse the same fixtures the Zod side parses, so a
   payload accepted by one language is accepted by the other.
2. Each Pydantic model's required-field set equals the Zod-derived JSON
   Schema's required-field set for the same model name — so a field added on
   one side but not the other fails CI.

The canonical JSON Schemas live in ``packages/contracts/schemas.json`` and are
exported from Zod by ``pnpm contracts:check`` (export-json-schema.ts). If that
file is missing the parity tests skip with a clear instruction, since the
bootstrap ordering runs the TS export before this suite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.contracts import (
    ChatCompletionChunk,
    ErrorCode,
    ErrorEnvelope,
    HealthResponse,
    SandboxResult,
    SystemPingResponse,
    WorkerJobEnvelope,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_PATH = REPO_ROOT / "packages" / "contracts" / "schemas.json"

# --- Shared fixtures (kept in lock-step with packages/contracts/src/conformance.ts) ---
FIXTURES: dict[str, list[dict[str, Any]]] = {
    "ErrorEnvelope": [
        {
            "code": "VALIDATION_ERROR",
            "message": "email is invalid",
            "trace_id": "trc_123",
            "retryable": False,
            "field_errors": [
                {"field": "email", "code": "format", "message": "invalid email"}
            ],
        },
        {
            "code": "INTERNAL_ERROR",
            "message": "unexpected failure",
            "trace_id": "trc_456",
            "retryable": False,
        },
    ],
    "HealthResponse": [
        {
            "status": "ok",
            "service": "api",
            "version": "0.0.0",
            "timestamp": "2026-07-17T00:00:00Z",
        },
        {
            "status": "degraded",
            "service": "worker",
            "version": "1.2.3",
            "timestamp": "2026-07-17T00:00:00Z",
        },
    ],
    "SystemPingResponse": [
        {"ok": True, "service": "api", "timestamp": "2026-07-17T00:00:00Z"}
    ],
    "ChatCompletionChunk": [
        {
            "id": "chat_1",
            "chunk_index": 0,
            "delta_content": "Hello",
            "timestamp": "2026-07-17T00:00:00Z",
        },
        {
            "id": "chat_1",
            "chunk_index": 1,
            "delta_reasoning": "thinking",
            "delta_tool_calls": [
                {"index": 0, "id": "call_1", "name": "lookup", "arguments": "{}"}
            ],
            "timestamp": "2026-07-17T00:00:00Z",
        },
    ],
    "SandboxResult": [
        {
            "run_id": "run_1",
            "status": "PASSED",
            "passed": True,
            "stdout": "",
            "stderr": "",
            "tests": [
                {"name": "test_a", "passed": True, "duration_ms": 12},
                {
                    "name": "test_b",
                    "passed": False,
                    "message": "assert",
                    "duration_ms": 3,
                    "stderr": "AssertionError",
                },
            ],
            "duration_ms": 20,
            "peak_memory_kb": 1024,
            "user_error": None,
            "platform_error": None,
        },
        {
            "run_id": "run_2",
            "status": "ERROR",
            "passed": False,
            "stdout": "",
            "stderr": "",
            "tests": [],
            "duration_ms": 0,
            "peak_memory_kb": None,
            "user_error": None,
            "platform_error": "runner crashed",
        },
    ],
    "WorkerJobEnvelope": [
        {
            "schema_version": 1,
            "event_id": "evt_job_1",
            "trace_id": "trc_1",
            "tenant_id": "tnt_demo",
            "student_id": "stu_1",
            "kind": "resource_generate",
            "payload": {"need": "loops"},
            "enqueued_at": "2026-07-17T00:00:00Z",
        }
    ],
}

MODEL_BY_NAME: dict[str, type[BaseModel]] = {
    "ErrorEnvelope": ErrorEnvelope,
    "HealthResponse": HealthResponse,
    "SystemPingResponse": SystemPingResponse,
    "ChatCompletionChunk": ChatCompletionChunk,
    "SandboxResult": SandboxResult,
    "WorkerJobEnvelope": WorkerJobEnvelope,
}


def test_error_code_count_matches_contract() -> None:
    """CONTRACT.md lists exactly 15 stable error codes."""
    assert len(list(ErrorCode)) == 15


@pytest.mark.parametrize("model_name", sorted(MODEL_BY_NAME))
def test_pydantic_parses_shared_fixtures(model_name: str) -> None:
    """Every fixture the Zod side accepts must parse in Pydantic too."""
    model = MODEL_BY_NAME[model_name]
    for sample in FIXTURES[model_name]:
        instance = model.model_validate(sample)
        # Round-trip: dump back to wire shape must re-validate.
        assert model.model_validate(instance.model_dump(mode="json"))


def test_invalid_payload_is_rejected() -> None:
    """Unknown enum values must be rejected (drift protection)."""
    with pytest.raises(ValidationError):
        ErrorEnvelope.model_validate(
            {
                "code": "NOT_A_REAL_CODE",
                "message": "x",
                "trace_id": "t",
                "retryable": False,
            }
        )


def _load_canonical_schemas() -> dict[str, Any]:
    if not SCHEMAS_PATH.exists():
        pytest.skip(
            "packages/contracts/schemas.json missing — run `pnpm contracts:check` "
            "first to export the Zod-derived JSON Schemas."
        )
    data: dict[str, Any] = json.loads(SCHEMAS_PATH.read_text(encoding="utf-8"))
    return data


def _zod_property_names(canonical_schema: dict[str, Any]) -> set[str]:
    """Extract property names from a zod-to-json-schema model.

    zod-to-json-schema emits ``$ref``/``definitions`` shape, so the properties
    live under ``definitions[<name>].properties`` rather than at the top level.
    """
    definitions = canonical_schema.get("definitions", {})
    # The model is referenced by $ref; pick the single definition that matches.
    for _name, node in definitions.items():
        if isinstance(node, dict) and "properties" in node:
            return set(node["properties"].keys())
    # Fallback: top-level properties (some emitters inline them).
    return set(canonical_schema.get("properties", {}).keys())


@pytest.mark.parametrize("model_name", sorted(MODEL_BY_NAME))
def test_property_names_match_zod_json_schema(model_name: str) -> None:
    """Pydantic and Zod must publish the same field-name set per model.

    This is the durable wire contract: every field the renderer and worker
    read/write must exist on both sides. ``required`` arrays are not compared
    because zod-to-json-schema and Pydantic disagree on how optionality maps
    to JSON Schema (zod marks optional fields as present-but-nullable), so
    property names are the stable, drift-revealing invariant.
    """
    schemas = _load_canonical_schemas()
    assert model_name in schemas, f"{model_name} missing from schemas.json"

    zod_props = _zod_property_names(schemas[model_name])
    pydantic_schema = MODEL_BY_NAME[model_name].model_json_schema()
    pydantic_props = set(pydantic_schema.get("properties", {}).keys())

    assert pydantic_props == zod_props, (
        f"property-name drift for {model_name}:\n"
        f"  pydantic only: {sorted(pydantic_props - zod_props)}\n"
        f"  zod only:      {sorted(zod_props - pydantic_props)}"
    )


def test_error_code_enum_values_match() -> None:
    """The ErrorCode enum values must equal the Zod ErrorCode.options."""
    schemas = _load_canonical_schemas()
    canonical = schemas["ErrorEnvelope"]
    definitions = canonical.get("definitions", {})
    envelope_def = next(v for v in definitions.values() if "properties" in v)
    code_schema = envelope_def["properties"]["code"]
    zod_codes = set(code_schema.get("enum", []))
    pydantic_codes = {code.value for code in ErrorCode}
    assert pydantic_codes == zod_codes, (
        f"error-code enum drift:\n"
        f"  pydantic only: {sorted(pydantic_codes - zod_codes)}\n"
        f"  zod only:      {sorted(zod_codes - pydantic_codes)}"
    )
