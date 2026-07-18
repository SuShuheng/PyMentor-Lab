"""Smoke tests for the Python runtime and production dependency boundary."""

import sys
import tomllib
from pathlib import Path

from app import __name__ as app_pkg
from app.contracts import __name__ as contracts_pkg


def test_python_version_is_313() -> None:
    """The frozen runtime target is Python 3.13.x."""
    assert sys.version_info >= (3, 13), f"expected >=3.13, got {sys.version_info}"


def test_backend_packages_importable() -> None:
    """The backend package layout resolves under pyproject pythonpath."""
    assert app_pkg == "app"
    assert contracts_pkg == "app.contracts"


def test_sandbox_http_client_is_a_production_dependency() -> None:
    """The API imports httpx at startup, so the runtime image must install it."""
    project_root = Path(__file__).resolve().parents[2]
    with (project_root / "pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)

    assert "httpx>=0.27" in project["project"]["dependencies"]
