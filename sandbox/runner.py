"""Typed adapter around the standard-library sandbox runtime harness."""

from __future__ import annotations

from typing import Any

from app.contracts.sandbox import SandboxExecutionRequest, SandboxResult
from sandbox.harness import execute_request as execute_raw_request


def execute_request(
    request: SandboxExecutionRequest | dict[str, Any],
) -> SandboxResult:
    validated = (
        request
        if isinstance(request, SandboxExecutionRequest)
        else SandboxExecutionRequest.model_validate(request)
    )
    raw = execute_raw_request(validated.model_dump(mode="json"))
    return SandboxResult.model_validate(raw)
