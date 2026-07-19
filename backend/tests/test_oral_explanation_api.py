"""BE-026 oral explanation scoring endpoint tests.

Composes BE-022 (TTS prompt) + BE-025 (ASR capture) + an LLM rubric to score a
student's verbal explanation. The result is recorded as evidence flowing through
the deterministic profile projection (INDEPENDENCE_SUPPORT, low confidence) and
NEVER advances mastery (CONTRACT rule). Mock-only: no live Xunfei/LLM
credential is ever authorized (INT-010 NOT-RUN).

The flow under test:

1. Server synthesizes the TTS prompt audio (mock → silent WAV + subtitle).
2. Server transcribes the student's recorded audio response (mock → stub).
3. Server scores the transcript with a deterministic mock rubric.
4. Server records ``ORAL_EXPLANATION_SCORED`` evidence and projects it to
   ``INDEPENDENCE_SUPPORT`` at low confidence; it does NOT call
   ``transition_mastery``.
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

from app.api.oral_explanation import (
    build_oral_object_store,
    get_asr_adapter_builder,
    get_tts_adapter_builder,
)
from app.contracts.oral import ORAL_RESPONSE_VIEW
from app.db import get_db
from app.main import create_app
from app.models import (
    EvidenceEvent,
    MasteryState,
    ProfileDimensionScore,
    ProfileVersion,
    User,
    UserStatus,
)
from app.provider_adapters import ProviderAdapterError
from app.provider_adapters.asr_xunfei import (
    MOCK_ASR_TRANSCRIPT,
    XunfeiAsrAdapter,
)
from app.provider_adapters.tts_xunfei import TTSXunfeiAdapter
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant

# A small non-empty "audio" payload — MOCK mode never decodes it.
_FAKE_AUDIO = b"\x49\x4e\x44\x58" * 64  # 256 bytes

# Stable master key so resolve_enabled_provider can run without a real operator
# secret (mirrors test_asr_api / test_tts_api).
_MASTER_KEY_B64 = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


@pytest.fixture(autouse=True)
def _provider_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYMENTOR_PROVIDER_MASTER_KEY", _MASTER_KEY_B64)


class _FakeObjectStore:
    """In-memory stand-in for ``MinioObjectStore`` (put + read_published)."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, *, key: str, content: bytes, mime_type: str, version: int):
        del mime_type, version
        self.objects[key] = bytes(content)
        import hashlib

        class _Stored:
            pass

        stored = _Stored()
        stored.key = key
        stored.digest = hashlib.sha256(content).hexdigest()
        return stored

    def read_published(self, key: str, expected_digest: str, *, max_bytes: int) -> bytes:
        del max_bytes
        return self.objects[key]


@pytest.fixture()
def client(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("PYMENTOR_PROVIDER_MASTER_KEY", _MASTER_KEY_B64)

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[build_oral_object_store] = lambda: _FakeObjectStore()
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
        email=f"oral-{uuid4().hex}@example.com",
        password_hash=hash_password(password),
    )
    user.status = UserStatus.ACTIVE
    db_session.flush()
    response = client.post("/api/v1/auth/login", json={"email": user.email, "password": password})
    assert response.status_code == 200, response.text
    return user, response.json()["access_token"]


def _headers(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _post(
    client: TestClient,
    token: str,
    *,
    node_id: str = str(uuid4()),
    prompt_text: str = "请解释 Python 的 for 循环是如何工作的。",
    audio: bytes = _FAKE_AUDIO,
    mime: str = "audio/webm",
    filename: str = "explanation.webm",
    expected_profile_version: int = 0,
    key: str | None = None,
):
    # The endpoint honors Idempotency-Key (required); default to a fresh key so
    # individual tests stay focused on the behavior under assertion.
    if key is None:
        key = f"oral-{uuid4().hex}"
    return client.post(
        "/api/v1/oral-explanation",
        headers=_headers(token, key=key),
        data={
            "node_id": node_id,
            "prompt_text": prompt_text,
            "expected_profile_version": expected_profile_version,
        },
        files={"file": (filename, io.BytesIO(audio), mime)},
    )


# ---------------------------------------------------------------------------
# Happy path — mock composition: TTS prompt + ASR transcript + LLM rubric
# ---------------------------------------------------------------------------


def test_oral_explanation_composes_tts_asr_rubric_and_projects_evidence(
    client: TestClient, db_session: Session
) -> None:
    """BE-026 happy path (mock mode).

    The endpoint synthesizes a TTS prompt (mock), transcribes the student's
    recording (mock stub transcript), scores it with the deterministic rubric
    (mock), records ``ORAL_EXPLANATION_SCORED`` evidence, and projects it to the
    ``INDEPENDENCE_SUPPORT`` dimension at low confidence. The response carries
    ``mock: True`` so a placeholder result is never confused for a live one.
    """

    user, token = _auth(client, db_session)
    node_id = uuid4()

    response = _post(
        client,
        token,
        node_id=str(node_id),
        key=f"oral-{uuid4().hex}",
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # Canonical wire shape — guards against drift.
    assert set(body) == ORAL_RESPONSE_VIEW
    # Mock labels surface at the top level and per-stage.
    assert body["mock"] is True
    assert body["prompt"]["mock"] is True
    assert body["transcript"]["provider_mode"] == "MOCK"
    # ASR mock transcript is reused verbatim (BE-025 stub).
    assert body["transcript"]["text"] == MOCK_ASR_TRANSCRIPT
    # Rubric is deterministic and populated.
    assert isinstance(body["score"], float)
    assert 0.0 <= body["score"] <= 1.0
    assert len(body["rubric"]) >= 1
    for item in body["rubric"]:
        assert {"criterion", "score", "feedback"} <= set(item)
        assert 0.0 <= item["score"] <= 1.0
    assert isinstance(body["model_answer"], str)
    assert body["model_answer"]
    # Evidence id is the canonical event id returned to the client.
    assert body["evidence_id"].startswith("evt_oral_")

    # Evidence was recorded with the right type and low confidence.
    evidence = db_session.scalar(
        select(EvidenceEvent).where(
            EvidenceEvent.tenant_id == user.tenant_id,
            EvidenceEvent.student_id == user.id,
            EvidenceEvent.event_type == "ORAL_EXPLANATION_SCORED",
        )
    )
    assert evidence is not None
    assert evidence.event_id == body["evidence_id"]
    assert evidence.node_id == node_id
    assert 0.0 < evidence.evidence_confidence < 0.5

    # Profile was projected onto INDEPENDENCE_SUPPORT at low confidence.
    profile = db_session.scalar(
        select(ProfileVersion).where(
            ProfileVersion.tenant_id == user.tenant_id,
            ProfileVersion.student_id == user.id,
        )
    )
    assert profile is not None
    assert profile.source_event_id == evidence.event_id
    dim = db_session.scalar(
        select(ProfileDimensionScore).where(
            ProfileDimensionScore.profile_version_id == profile.id,
        )
    )
    assert dim is not None
    assert dim.dimension.value == "INDEPENDENCE_SUPPORT"
    assert 0.0 <= dim.score <= 1.0
    assert 0.0 < dim.confidence < 0.5

    # NEVER auto-advance mastery — no MasteryState rows touched.
    mastery = db_session.scalar(
        select(MasteryState).where(
            MasteryState.tenant_id == user.tenant_id,
            MasteryState.student_id == user.id,
        )
    )
    assert mastery is None


def test_oral_explanation_default_builders_are_mock_adapters() -> None:
    """The endpoint's default dependency factories return the real mock adapters.

    This pins the wiring so a future refactor cannot accidentally swap in a live
    adapter without updating the contract; the default builders must construct
    the same mock-mode adapters used by BE-022 / BE-025.
    """

    tts_builder = get_tts_adapter_builder()
    asr_builder = get_asr_adapter_builder()
    assert isinstance(tts_builder(None), TTSXunfeiAdapter)
    assert isinstance(asr_builder(None), XunfeiAsrAdapter)
    assert tts_builder(None).mock is True
    assert asr_builder(None).is_mock is True


# ---------------------------------------------------------------------------
# Auth + tenant scoping
# ---------------------------------------------------------------------------


def test_oral_explanation_requires_student_auth(client: TestClient) -> None:
    anonymous = client.post(
        "/api/v1/oral-explanation",
        data={"node_id": str(uuid4()), "prompt_text": "explain loops"},
        files={"file": ("q.webm", io.BytesIO(_FAKE_AUDIO), "audio/webm")},
    )
    assert anonymous.status_code == 401, anonymous.text
    assert anonymous.json()["code"] == "AUTH_REQUIRED"


def test_oral_explanation_rejects_empty_audio(client: TestClient, db_session: Session) -> None:
    _, token = _auth(client, db_session)
    response = _post(client, token, audio=b"")
    assert response.status_code == 422, response.text


def test_oral_explanation_rejects_disallowed_mime(client: TestClient, db_session: Session) -> None:
    _, token = _auth(client, db_session)
    response = _post(client, token, mime="video/mp4", filename="q.mp4")
    assert response.status_code == 415, response.text
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Idempotency — replay returns the cached response
# ---------------------------------------------------------------------------


def test_oral_explanation_is_idempotent_under_key(client: TestClient, db_session: Session) -> None:
    """Idempotency-Key honored: replay returns the cached response byte-for-byte
    (same evidence_id) and does not double-write evidence."""

    _, token = _auth(client, db_session)
    key = f"oral-{uuid4().hex}"

    first = _post(client, token, key=key)
    second = _post(client, token, key=key)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["evidence_id"] == second.json()["evidence_id"]


# ---------------------------------------------------------------------------
# Degraded path — TTS or ASR live failure surfaces as PROVIDER_UNAVAILABLE (503)
# ---------------------------------------------------------------------------


class _FailingTtsAdapter:
    """Always raises — simulates an unauthorized live TTS provider."""

    mock = False

    def generate(self, text, voice_options=None):  # pragma: no cover - failure path
        del text, voice_options
        raise ProviderAdapterError("tts upstream unreachable")


class _FailingAsrAdapter:
    """Always raises — simulates an unauthorized live ASR provider."""

    is_mock = False

    def transcribe(self, audio_bytes, mime):  # pragma: no cover - failure path
        del audio_bytes, mime
        raise ProviderAdapterError("asr upstream unreachable")


def test_oral_explanation_tts_failure_returns_503(client: TestClient, db_session: Session) -> None:
    _, token = _auth(client, db_session)
    app: FastAPI = client.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_tts_adapter_builder] = lambda: (
        lambda provider: _FailingTtsAdapter()
    )
    try:
        response = _post(client, token)
    finally:
        app.dependency_overrides.pop(get_tts_adapter_builder, None)

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["code"] == "PROVIDER_UNAVAILABLE"
    assert body["retryable"] is True
    assert "upstream unreachable" not in response.text


def test_oral_explanation_asr_failure_returns_503(client: TestClient, db_session: Session) -> None:
    _, token = _auth(client, db_session)
    app: FastAPI = client.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_asr_adapter_builder] = lambda: (
        lambda provider: _FailingAsrAdapter()
    )
    try:
        response = _post(client, token)
    finally:
        app.dependency_overrides.pop(get_asr_adapter_builder, None)

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["code"] == "PROVIDER_UNAVAILABLE"
    assert "upstream unreachable" not in response.text


# ---------------------------------------------------------------------------
# Stale profile version — surfaces as typed CONFLICT (409)
# ---------------------------------------------------------------------------


def test_oral_explanation_stale_profile_version_returns_409(
    client: TestClient, db_session: Session
) -> None:
    _, token = _auth(client, db_session)

    # First submission projects the profile to version 1.
    first = _post(client, token, expected_profile_version=0, key=f"oral-{uuid4().hex}")
    assert first.status_code == 200, first.text

    # A second submission carrying the now-stale expected_version=0 conflicts.
    second = _post(client, token, expected_profile_version=0, key=f"oral-{uuid4().hex}")
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "CONFLICT"
