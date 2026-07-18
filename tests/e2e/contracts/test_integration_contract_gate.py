"""Cross-lane transport-contract gates owned by the integration workstream."""

from __future__ import annotations

import json
from pathlib import Path

from app.main import create_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_WORKSPACE_PACKAGES = (
    "apps/web",
    "apps/admin",
    "packages/ui",
    "packages/charts",
    "packages/config",
)


def test_frontend_projects_are_part_of_the_root_workspace() -> None:
    workspace = (REPOSITORY_ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8")

    missing = [path for path in FRONTEND_WORKSPACE_PACKAGES if f'"{path}"' not in workspace]

    assert missing == [], f"frontend projects missing from pnpm workspace: {missing}"


def test_renderers_consume_the_generated_api_client() -> None:
    missing: list[str] = []
    for renderer in ("apps/web", "apps/admin"):
        manifest = json.loads(
            (REPOSITORY_ROOT / renderer / "package.json").read_text(encoding="utf-8")
        )
        if "@pymentor/api-client" not in manifest.get("dependencies", {}):
            missing.append(renderer)

    assert missing == [], f"renderers missing @pymentor/api-client dependency: {missing}"


def test_committed_openapi_document_matches_the_integrated_fastapi_app() -> None:
    committed = json.loads(
        (REPOSITORY_ROOT / "packages/api-client/openapi.json").read_text(encoding="utf-8")
    )

    assert committed == create_app().openapi(), (
        "packages/api-client/openapi.json is stale; regenerate the API client in the backend lane"
    )
