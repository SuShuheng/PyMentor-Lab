"""BE-025 Xunfei ASR adapter + ``POST /api/v1/asr`` endpoint tests.

Mock-only: no live Xunfei credential is ever authorized (INT-010 NOT-RUN).
Raw audio is NEVER persisted — only audit/observability metadata is recorded.
Shape parity with BE-022 (TTS) and BE-024 (OCR).
"""

from __future__ import annotations

import base64
import io
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.asr import get_asr_adapter_builder
from app.contracts.asr import (
    ASR_MAX_AUDIO_BYTES,
    ASR_RESPONSE_VIEW,
    ASRResult,
)
from app.db import get_db
from app.main import create_app
from app.models import AuditEvent, User, UserStatus
from app.provider_adapters import ProviderAdapterError
from app.provider_adapters.asr_xunfei import (
    MOCK_ASR_CONFIDENCE,
    MOCK_ASR_LANGUAGE,
    MOCK_ASR_TRANSCRIPT,
    XunfeiAsrAdapter,
)
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant

# A small, non-empty "audio" payload — MOCK mode never decodes it.
_FAKE_AUDIO = b"\x49\x4e\x44\x58" * 64  # 256 bytes

# The endpoint resolves the BE-019 provider row to decide mock vs live; even in
# mock mode (no row) it must decode the master key once. Provide a deterministic
# 32-byte key so the resolve path does not 503 (matches the provider_config_api
# fixture pattern).
_MASTER_KEY_B64 = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


@pytest.fixture(autouse=True)
def _provider_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYMENTOR_PROVIDER_MASTER_KEY", _MASTER_KEY_B64)


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
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
        email=f"asr-{uuid4().hex}@example.com",
        password_hash=hash_password(password),
    )
    user.status = UserStatus.ACTIVE
    db_session.flush()
    response = client.post("/api/v1/auth/login", json={"email": user.email, "password": password})
    assert response.status_code == 200, response.text
    return user, response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _upload(
    client: TestClient,
    token: str,
    *,
    audio: bytes = _FAKE_AUDIO,
    mime: str = "audio/webm",
    filename: str = "question.webm",
):
    return client.post(
        "/api/v1/asr",
        headers=_headers(token),
        files={"file": (filename, io.BytesIO(audio), mime)},
    )


# ---------------------------------------------------------------------------
# Adapter (unit) — MOCK mode is deterministic and never touches the network.
# ---------------------------------------------------------------------------


def test_mock_adapter_returns_deterministic_transcript_and_duration() -> None:
    adapter = XunfeiAsrAdapter(provider=None)
    assert adapter.is_mock is True

    result = adapter.transcribe(_FAKE_AUDIO, "audio/webm")

    assert isinstance(result, ASRResult)
    assert result.transcript == MOCK_ASR_TRANSCRIPT
    assert result.language == MOCK_ASR_LANGUAGE
    assert result.confidence == MOCK_ASR_CONFIDENCE
    assert result.provider_mode == "MOCK"
    # Stub duration is populated and within the endpoint's 60s limit.
    assert 0 < result.duration_ms <= 60_000


def test_mock_adapter_rejects_empty_audio() -> None:
    adapter = XunfeiAsrAdapter(provider=None)
    with pytest.raises(ValueError, match="empty audio payload"):
        adapter.transcribe(b"", "audio/webm")


def test_live_adapter_without_credential_fails_closed_with_typed_error() -> None:
    """LIVE mode requires an authorized credential; it fails closed.

    When a provider row IS resolved (so ``is_mock`` is False) but the live
    branch is not configured (INT-010 NOT-RUN), the adapter raises
    ``ProviderAdapterError`` rather than returning a fake transcript. The API
    layer maps this to PROVIDER_UNAVAILABLE (503) so the student falls back to
    typing. The live network call itself is never exercised from unit tests.
    """
    from uuid import uuid4

    from app.providers import ProviderType, ResolvedProvider

    provider = ResolvedProvider(
        id=uuid4(),
        tenant_id=uuid4(),
        provider_type=ProviderType.ASR,
        vendor="xfyun",
        model="spark-asr",
        api_key="not-authorized-in-ci",
        endpoint="https://api.xf-yun.com/v1/asr",
        params={},
    )
    adapter = XunfeiAsrAdapter(provider=provider)
    assert adapter.is_mock is False
    with pytest.raises(ProviderAdapterError):
        adapter.transcribe(_FAKE_AUDIO, "audio/webm")


# ---------------------------------------------------------------------------
# Endpoint — happy path, MIME allowlist, size/duration limits, auth, degraded.
# ---------------------------------------------------------------------------


def test_asr_endpoint_returns_transcript_and_does_not_persist_audio(
    client: TestClient, db_session: Session
) -> None:
    """BE-025: POST /api/v1/asr transcribes audio and returns the stub text.

    The raw audio is NEVER persisted: only an audit row with metadata
    (mime, size, duration, provider mode) is written. The transcript text
    matches the canonical contract view shape.
    """
    user, token = _auth(client, db_session)

    response = _upload(client, token)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transcript"] == MOCK_ASR_TRANSCRIPT
    assert body["confidence"] == MOCK_ASR_CONFIDENCE
    assert body["language"] == MOCK_ASR_LANGUAGE
    assert isinstance(body["duration_ms"], int)
    assert 0 < body["duration_ms"] <= 60_000
    assert body["provider_mode"] == "MOCK"
    # The view is the canonical contract for ASR responses.
    assert set(body) == ASR_RESPONSE_VIEW

    # Audit metadata only — raw audio bytes are NOT in any stored row.
    audit = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == user.tenant_id,
            AuditEvent.actor_user_id == user.id,
            AuditEvent.action == "ASR_TRANSCRIPTION",
        )
    )
    assert audit is not None
    assert audit.resource_type == "asr"
    detail = audit.detail
    assert detail["mime"] == "audio/webm"
    assert detail["provider_mode"] == "MOCK"
    assert detail["size_bytes"] == len(_FAKE_AUDIO)
    # Raw audio must never leak into audit detail.
    assert "audio" not in detail
    assert _FAKE_AUDIO.hex() not in str(detail)
    assert _FAKE_AUDIO.decode("latin-1", errors="ignore") not in str(detail)


def test_asr_confidence_and_language_are_optional_in_contract() -> None:
    result = ASRResult(transcript="hello", duration_ms=1_000)
    assert result.confidence is None
    assert result.language is None
    assert result.provider_mode == "MOCK"


def test_asr_endpoint_rejects_disallowed_mime(client: TestClient, db_session: Session) -> None:
    _, token = _auth(client, db_session)
    response = _upload(client, token, mime="video/mp4", filename="q.mp4")
    assert response.status_code == 415, response.text
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "unsupported audio type" in body["message"]


def test_asr_endpoint_rejects_oversized_payload(client: TestClient, db_session: Session) -> None:
    _, token = _auth(client, db_session)
    # 10 MiB limit → 10 MiB + 1 byte is rejected before transcription.
    oversized = b"\x00" * (ASR_MAX_AUDIO_BYTES + 1)
    response = _upload(client, token, audio=oversized)
    assert response.status_code == 413, response.text


def test_asr_endpoint_rejects_empty_upload(client: TestClient, db_session: Session) -> None:
    _, token = _auth(client, db_session)
    response = _upload(client, token, audio=b"")
    assert response.status_code == 422, response.text


def test_asr_endpoint_requires_student_auth(client: TestClient) -> None:
    anonymous = client.post(
        "/api/v1/asr",
        files={"file": ("q.webm", io.BytesIO(_FAKE_AUDIO), "audio/webm")},
    )
    assert anonymous.status_code == 401, anonymous.text
    assert anonymous.json()["code"] == "AUTH_REQUIRED"


# ---------------------------------------------------------------------------
# Degraded path — live provider failure surfaces as PROVIDER_UNAVAILABLE (503)
# ---------------------------------------------------------------------------


class _FailingAdapter:
    is_mock = False

    def transcribe(self, audio_bytes: bytes, mime: str) -> ASRResult:  # pragma: no cover
        del audio_bytes, mime
        raise ProviderAdapterError("upstream unreachable")


def test_asr_provider_failure_returns_503(client: TestClient, db_session: Session) -> None:
    """Degraded: when the provider cannot service the request, the endpoint
    returns a typed 503 PROVIDER_UNAVAILABLE so the notebook keeps working
    (the student can always type the question instead)."""
    user, token = _auth(client, db_session)
    app: FastAPI = client.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_asr_adapter_builder] = lambda: lambda provider: _FailingAdapter()
    try:
        response = _upload(client, token)
    finally:
        app.dependency_overrides.pop(get_asr_adapter_builder, None)

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["code"] == "PROVIDER_UNAVAILABLE"
    assert body["retryable"] is True
    # The raw error text must not escape; only the stable message is echoed.
    assert "upstream unreachable" not in response.text
    _ = user
