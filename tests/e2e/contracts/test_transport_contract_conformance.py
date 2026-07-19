from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from app.contracts import (
    AgentProposalEnvelope,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ErrorEnvelope,
    SandboxExecutionResponse,
    StreamEvent,
    WorkerJobEnvelope,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "transport-contract-cases.json"
FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
ADAPTERS = {
    "AgentProposalEnvelope": TypeAdapter(AgentProposalEnvelope),
    "ChatCompletionRequest": TypeAdapter(ChatCompletionRequest),
    "ErrorEnvelope": TypeAdapter(ErrorEnvelope),
    "SandboxExecutionResponse": TypeAdapter(SandboxExecutionResponse),
    "StreamEvent": TypeAdapter(StreamEvent),
    "WorkerJobEnvelope": TypeAdapter(WorkerJobEnvelope),
}


def _accepts(adapter: TypeAdapter[Any], payload: object) -> bool:
    try:
        adapter.validate_python(payload)
    except ValidationError:
        return False
    return True


@pytest.mark.parametrize(
    "fixture",
    FIXTURES["schema_cases"],
    ids=lambda fixture: fixture["id"],
)
def test_pydantic_matches_schema_fixture_expectation(fixture: dict[str, Any]) -> None:
    accepted = _accepts(ADAPTERS[fixture["schema"]], fixture["payload"])
    assert accepted is (fixture["expected"] == "accept")


@pytest.mark.parametrize(
    "fixture",
    FIXTURES["stream_sequences"],
    ids=lambda fixture: fixture["id"],
)
def test_pydantic_enforces_monotonic_stream_chunk_order(fixture: dict[str, Any]) -> None:
    try:
        chunks = [ChatCompletionChunk.model_validate(chunk) for chunk in fixture["chunks"]]
    except ValidationError:
        accepted = False
    else:
        accepted = all(chunk.chunk_index == index for index, chunk in enumerate(chunks))
    assert accepted is (fixture["expected"] == "accept")


def test_zod_matches_the_same_fixture_expectations() -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the cross-language contract gate"
    tsx_cli = REPO_ROOT / "node_modules" / "tsx" / "dist" / "cli.mjs"
    assert tsx_cli.is_file(), "run pnpm install --frozen-lockfile before the contract gate"

    completed = subprocess.run(
        [node, str(tsx_cli), "scripts/acceptance/transport-contract-conformance.ts"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
