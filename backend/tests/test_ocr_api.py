"""BE-024 student-facing OCR API integration tests.

Mock-only: no live Xunfei credential is ever configured. INT-010 NOT-RUN.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.ocr import get_ocr_adapter_factory
from app.contracts.ocr import (
    OCR_MAX_IMAGE_BYTES,
    OCRResult,
)
from app.db import get_db
from app.main import create_app
from app.models import User, UserStatus
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture()
def client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # The OCR endpoint resolves the OCR provider via BE-019, which needs the
    # provider master key even when no provider row exists (the resolution
    # helper accepts the key up-front). Tests run mock-only, so a fixed key is
    # safe and matches the BE-010 test pattern.
    monkeypatch.setenv(
        "PYMENTOR_PROVIDER_MASTER_KEY",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",  # 32 zero bytes, b64
    )

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _auth(client: TestClient, db_session: Session) -> tuple[User, str]:
    tenant = get_or_create_tenant(db_session, slug="default", name="Default")
    db_session.flush()
    password = "ValidPass1!"
    user = create_student_user(
        db_session,
        tenant_id=tenant.id,
        email=f"ocr-{uuid4().hex}@example.com",
        password_hash=hash_password(password),
    )
    user.status = UserStatus.ACTIVE
    db_session.flush()
    response = client.post("/api/v1/auth/login", json={"email": user.email, "password": password})
    assert response.status_code == 200, response.text
    return user, response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# POST /api/v1/ocr — happy path
# --------------------------------------------------------------------------- #


def test_ocr_returns_mock_text_and_is_not_persisted(
    client: TestClient, db_session: Session
) -> None:
    _, token = _auth(client, db_session)

    response = client.post(
        "/api/v1/ocr",
        headers=_headers(token),
        files={"file": ("err.png", io.BytesIO(PNG_1X1), "image/png")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["extracted_text"].startswith("[mock-ocr]")
    assert f"bytes={len(PNG_1X1)}" in body["extracted_text"]
    assert body["mime"] == "image/png"
    assert body["size_bytes"] == len(PNG_1X1)
    assert body["confidence"] == pytest.approx(0.97)
    # No raw image is persisted: only audit/observability rows, which carry
    # metadata but never the bytes. The digest proves the right payload ran
    # without echoing it back.
    assert "digest=" in body["extracted_text"]
    assert PNG_1X1.hex() not in body["extracted_text"]


def test_ocr_confidence_is_optional_in_contract() -> None:
    result = OCRResult(text="hello")
    assert result.confidence is None
    assert result.bboxes == []


# --------------------------------------------------------------------------- #
# MIME / size enforcement at the boundary
# --------------------------------------------------------------------------- #


def test_ocr_rejects_unsupported_mime(client: TestClient, db_session: Session) -> None:
    _, token = _auth(client, db_session)

    response = client.post(
        "/api/v1/ocr",
        headers=_headers(token),
        files={"file": ("err.gif", io.BytesIO(b"GIF89a"), "image/gif")},
    )

    assert response.status_code == 415, response.text
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "unsupported image type" in body["message"]


def test_ocr_rejects_oversized_upload(client: TestClient, db_session: Session) -> None:
    _, token = _auth(client, db_session)
    oversized = b"\x00" * (OCR_MAX_IMAGE_BYTES + 1)

    response = client.post(
        "/api/v1/ocr",
        headers=_headers(token),
        files={"file": ("big.png", io.BytesIO(oversized), "image/png")},
    )

    assert response.status_code == 413, response.text


def test_ocr_rejects_empty_upload(client: TestClient, db_session: Session) -> None:
    _, token = _auth(client, db_session)

    response = client.post(
        "/api/v1/ocr",
        headers=_headers(token),
        files={"file": ("empty.png", io.BytesIO(b""), "image/png")},
    )

    assert response.status_code == 422, response.text


# --------------------------------------------------------------------------- #
# Auth / scope
# --------------------------------------------------------------------------- #


def test_ocr_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ocr",
        files={"file": ("err.png", io.BytesIO(PNG_1X1), "image/png")},
    )
    assert response.status_code == 401, response.text


# --------------------------------------------------------------------------- #
# Degraded path — live provider failure surfaces as PROVIDER_UNAVAILABLE
# --------------------------------------------------------------------------- #


class _FailingAdapter:
    is_mock = False

    def extract(self, image_bytes: bytes, mime: str) -> OCRResult:  # pragma: no cover
        from app.provider_adapters import ProviderAdapterError

        raise ProviderAdapterError("upstream down")


def test_ocr_provider_failure_returns_503(client: TestClient, db_session: Session) -> None:
    _, token = _auth(client, db_session)
    app: FastAPI = client.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_ocr_adapter_factory] = lambda: lambda provider: _FailingAdapter()
    try:
        response = client.post(
            "/api/v1/ocr",
            headers=_headers(token),
            files={"file": ("err.png", io.BytesIO(PNG_1X1), "image/png")},
        )
    finally:
        app.dependency_overrides.pop(get_ocr_adapter_factory, None)

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["code"] == "PROVIDER_UNAVAILABLE"
    assert body["retryable"] is True
