"""Service health and connectivity contracts (Pydantic mirror).

Mirror of ``packages/contracts/src/health.ts``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class HealthResponse(BaseModel):
    """Body of ``GET /health``."""

    model_config = ConfigDict(extra="forbid")

    status: HealthStatus
    service: str = Field(min_length=1)
    version: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)


class SystemPingResponse(BaseModel):
    """Body of the public ``GET /system/ping`` connectivity-test endpoint."""

    model_config = ConfigDict(extra="forbid")

    ok: Literal[True] = True
    service: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)
