"""Regression gates for the workspace and generated API client boundary."""

from __future__ import annotations

import json
from pathlib import Path

from app.main import create_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DECLARED_WORKSPACE_PROJECTS = (
    "apps/web",
    "apps/admin",
    "apps/desktop",
    "packages/ui",
    "packages/charts",
    "packages/config",
    "packages/contracts",
    "packages/api-client",
)


def test_workspace_includes_all_declared_projects() -> None:
    workspace = (REPOSITORY_ROOT / "pnpm-workspace.yaml").read_text(
        encoding="utf-8"
    )

    missing = [
        project
        for project in DECLARED_WORKSPACE_PROJECTS
        if f'"{project}"' not in workspace
    ]

    assert missing == [], f"projects missing from pnpm workspace: {missing}"


def test_committed_openapi_matches_current_fastapi_app() -> None:
    committed = json.loads(
        (REPOSITORY_ROOT / "packages/api-client/openapi.json").read_text(
            encoding="utf-8"
        )
    )

    assert committed == create_app().openapi(), (
        "packages/api-client/openapi.json is stale; run the canonical generator"
    )
