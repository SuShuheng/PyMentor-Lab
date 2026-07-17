"""Export the FastAPI OpenAPI spec to a JSON file for client generation.

Run: ``uv run python scripts/export_openapi.py``.
The output is consumed by ``pnpm contracts:gen`` (openapi-ts) to regenerate the
TypeScript API client. This script never starts a server — it reads the schema
directly from the app factory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the backend app package is importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import create_app  # noqa: E402

OUTPUT = Path(__file__).resolve().parents[1] / "packages" / "api-client" / "openapi.json"


def main() -> int:
    app = create_app()
    spec = app.openapi()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(spec.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
