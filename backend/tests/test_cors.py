"""Browser CORS boundary tests for the student and admin renderers."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_trusted_renderer_origin_can_make_credentialed_preflight() -> None:
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.options(
            "/api/v1/auth/me",
            headers={
                "Origin": "http://127.0.0.1:4173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4173"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "GET" in response.headers["access-control-allow-methods"]
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_untrusted_renderer_origin_is_not_granted_cors_access() -> None:
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.options(
            "/api/v1/auth/me",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert "access-control-allow-origin" not in response.headers


def test_deployment_can_replace_the_explicit_renderer_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PYMENTOR_CORS_ALLOWED_ORIGINS",
        "https://student.pymentor.dev, https://admin.pymentor.dev",
    )
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.options(
            "/api/v1/auth/me",
            headers={
                "Origin": "https://admin.pymentor.dev",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://admin.pymentor.dev"


def test_wildcard_origin_is_rejected_when_credentials_are_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYMENTOR_CORS_ALLOWED_ORIGINS", "*")

    with pytest.raises(ValueError, match="explicit origins"):
        create_app()
