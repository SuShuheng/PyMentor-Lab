"""Smoke test: the Python toolchain (3.13) and project import resolve."""

import sys

from app import __name__ as app_pkg
from app.contracts import __name__ as contracts_pkg


def test_python_version_is_313() -> None:
    """The frozen runtime target is Python 3.13.x."""
    assert sys.version_info >= (3, 13), f"expected >=3.13, got {sys.version_info}"


def test_backend_packages_importable() -> None:
    """The backend package layout resolves under pyproject pythonpath."""
    assert app_pkg == "app"
    assert contracts_pkg == "app.contracts"
