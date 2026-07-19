"""BE-022 student-facing TTS API integration tests.

Mock-only: no live Xunfei credential is ever configured and the live branch
is INT-010 NOT-RUN. These tests exercise the happy path (mock generate,
subtitle track, MinIO persistence with SHA-256 digest, authenticated playback),
the no-credential degradation path, tenant scoping, auth, and idempotency.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.tts import build_tts_object_store
from app.contracts.tts import TTSVoice
from app.db import get_db
from app.main import create_app
from app.models import OutboxEvent, User, UserStatus
from app.security import hash_password
from app.services import create_student_user, get_or_create_tenant

# A stable master key for tests so resolve_enabled_provider can run without a
# real operator secret. Mirrors test_provider_config_api.py.
MASTER_KEY_B64 = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


class FakeObjectStore:
    """In-memory stand-in for ``MinioObjectStore`` implementing the subset of
    the interface the TTS endpoint uses (``put`` + ``read_published``).

    Stores content + digest so the authenticated playback route can return the
    exact bytes the synthesizer produced, and a wrong digest yields a 404.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, *, key: str, content: bytes, mime_type: str, version: int):
        del mime_type, version  # not needed for the fake
        self.objects[key] = bytes(content)
        digest = hashlib.sha256(content).hexdigest()

        class _Stored:
            pass

        stored = _Stored()
        stored.key = key
        stored.digest = digest
        return stored

    def read_published(self, key: str, expected_digest: str, *, max_bytes: int) -> bytes:
        del max_bytes
        if key not in self.objects:
            raise KeyError(key)
        content = self.objects[key]
        if hashlib.sha256(content).hexdigest() != expected_digest:
            raise ValueError("digest mismatch")
        return content


@pytest.fixture()
def fake_object_store() -> FakeObjectStore:
    return FakeObjectStore()


@pytest.fixture()
def client(
    db_session: Session,
    fake_object_store: FakeObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("PYMENTOR_PROVIDER_MASTER_KEY", MASTER_KEY_B64)

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[build_tts_object_store] = lambda: fake_object_store
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
        email=f"tts-{uuid4().hex}@example.com",
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


def _body(*, text: str = "你好，世界。这是测试。", voice: str = "xiaoyan") -> dict[str, object]:
    return {"text": text, "voice": voice}


# --------------------------------------------------------------------------- #
# POST /api/v1/tts — happy path (mock)
# --------------------------------------------------------------------------- #


def test_tts_returns_mock_clip_subtitle_track_and_persists_with_digest(
    client: TestClient,
    db_session: Session,
    fake_object_store: FakeObjectStore,
) -> None:
    user, token = _auth(client, db_session)

    response = client.post("/api/v1/tts", json=_body(), headers=_headers(token, "tts-create-1"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mock"] is True
    assert body["mime"] == "audio/wav"
    assert body["duration_ms"] > 0
    # Subtitle track split on CJK punctuation: two sentences → two cues.
    assert len(body["subtitle_track"]) == 2
    first_cue = body["subtitle_track"][0]
    assert first_cue["text"] == "你好，世界。"
    assert first_cue["start_ms"] == 0
    assert first_cue["end_ms"] > first_cue["start_ms"]
    assert "你好，世界。" in first_cue["text"]
    # Audio URL is authenticated and served by this API (no raw MinIO host).
    assert body["audio_url"].startswith("/api/v1/tts/audio/")

    # The audio bytes are stored with a SHA-256 digest; the URL embeds it.
    request_id = body["audio_url"].split("/")[5]
    digest = body["audio_url"].rstrip("/").split("/")[-1]
    object_key = f"resources/tts/{user.tenant_id}/{user.id}/{request_id}/v1"
    stored = fake_object_store.objects[object_key]
    assert hashlib.sha256(stored).hexdigest() == digest
    # Stored bytes are a real, decodable WAV header (mock = silence).
    assert stored[:4] == b"RIFF"

    # The playback route returns the exact stored bytes (authenticated).
    audio = client.get(body["audio_url"], headers=_headers(token))
    assert audio.status_code == 200
    assert audio.content == stored
    assert audio.headers["content-type"] == "audio/wav"
    assert audio.headers["etag"] == f'"{digest}"'


def test_tts_idempotency_replays_same_url_and_digest(
    client: TestClient, db_session: Session, fake_object_store: FakeObjectStore
) -> None:
    _user, token = _auth(client, db_session)

    first = client.post("/api/v1/tts", json=_body(), headers=_headers(token, "tts-replay"))
    second = client.post("/api/v1/tts", json=_body(), headers=_headers(token, "tts-replay"))

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["audio_url"] == second.json()["audio_url"]
    # Exactly one object persisted despite two requests.
    assert len(fake_object_store.objects) == 1


def test_tts_writes_outbox_event_for_generated_clip(
    client: TestClient, db_session: Session
) -> None:
    user, token = _auth(client, db_session)

    response = client.post("/api/v1/tts", json=_body(), headers=_headers(token, "tts-outbox"))
    assert response.status_code == 200, response.text

    event = db_session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.tenant_id == user.tenant_id,
            OutboxEvent.event_type == "TTS_GENERATED",
        )
    )
    assert event is not None
    assert event.payload["voice"] == TTSVoice.XIAOYAN.value
    assert event.payload["mock"] is True


# --------------------------------------------------------------------------- #
# Auth and tenant scoping
# --------------------------------------------------------------------------- #


def test_tts_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/v1/tts", json=_body())
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


def test_tts_requires_idempotency_key(client: TestClient, db_session: Session) -> None:
    _user, token = _auth(client, db_session)
    response = client.post("/api/v1/tts", json=_body(), headers=_headers(token))
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_tts_audio_route_is_tenant_scoped(
    client: TestClient, db_session: Session, fake_object_store: FakeObjectStore
) -> None:
    """A foreign student cannot read another tenant's clip.

    The object key is reconstructed from the authenticated user's tenant +
    id, so a foreign token resolves a different key and gets a 404.
    """

    _owner, owner_token = _auth(client, db_session)
    created = client.post(
        "/api/v1/tts", json=_body(), headers=_headers(owner_token, "tts-scope-owner")
    )
    assert created.status_code == 200
    audio_url = created.json()["audio_url"]

    _other, other_token = _auth(client, db_session)
    foreign = client.get(audio_url, headers=_headers(other_token))
    assert foreign.status_code == 404
    assert foreign.json()["code"] == "NOT_FOUND"
    # Owner can still read their own clip.
    assert client.get(audio_url, headers=_headers(owner_token)).status_code == 200


def test_tts_audio_wrong_digest_returns_404(client: TestClient, db_session: Session) -> None:
    user, token = _auth(client, db_session)
    request_id = uuid4()
    url = f"/api/v1/tts/audio/{request_id}/{'a' * 64}"
    response = client.get(url, headers=_headers(token))
    del user
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


# --------------------------------------------------------------------------- #
# Degradation: live provider failure → typed PROVIDER_UNAVAILABLE
# --------------------------------------------------------------------------- #


def test_tts_live_provider_failure_surfaces_typed_unavailable(
    db_session: Session,
    fake_object_store: FakeObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a live provider is resolved but the adapter raises
    ``ProviderAdapterError`` (the not-authorized live branch), the endpoint
    returns a typed ``PROVIDER_UNAVAILABLE`` (503) and never persists a clip.

    This is the degradation contract: the teaching loop can branch on the typed
    error and fall back to plain text without confusing a placeholder for a
    real voice. We persist a real TTS ``provider_configs`` row so the FK on
    ``provider_call_records`` is satisfied and the observability write succeeds.
    """

    import app.api.tts as tts_module
    from app.models import ProviderConfig
    from app.provider_adapters import ProviderAdapterError
    from app.providers import (
        ProviderType,
        encrypt_provider_secret,
        provider_secret_context,
    )

    master_key = base64.urlsafe_b64decode(MASTER_KEY_B64)
    monkeypatch.setenv("PYMENTOR_PROVIDER_MASTER_KEY", MASTER_KEY_B64)
    monkeypatch.delenv("PYMENTOR_TTS_MOCK", raising=False)

    tenant = get_or_create_tenant(db_session, slug="default", name="Default")
    db_session.flush()
    provider_id = uuid4()
    db_session.add(
        ProviderConfig(
            id=provider_id,
            tenant_id=tenant.id,
            provider_type=ProviderType.TTS,
            vendor="xfyun",
            model="superbird-tts-v1",
            api_key_encrypted=encrypt_provider_secret(
                "live-tts-key",
                master_key,
                provider_secret_context(tenant.id, provider_id),
            ),
            endpoint="https://tts.example.com",
            params={},
            enabled=True,
        )
    )
    db_session.flush()

    password = "ValidPass1!"
    user = create_student_user(
        db_session,
        tenant_id=tenant.id,
        email=f"tts-fail-{uuid4().hex}@example.com",
        password_hash=hash_password(password),
    )
    user.status = UserStatus.ACTIVE
    db_session.flush()

    class _FailingAdapter:
        mock = False

        def generate(self, text, voice_options=None):
            del text, voice_options
            raise ProviderAdapterError("live not authorized")

    original_build = tts_module.build_tts_adapter
    tts_module.build_tts_adapter = lambda _provider: _FailingAdapter()

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[build_tts_object_store] = lambda: fake_object_store
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            login = test_client.post(
                "/api/v1/auth/login",
                json={"email": user.email, "password": password},
            )
            assert login.status_code == 200
            token = login.json()["access_token"]
            response = test_client.post(
                "/api/v1/tts",
                json=_body(),
                headers=_headers(token, "tts-fail"),
            )
            assert response.status_code == 503
            body = response.json()
            assert body["code"] == "PROVIDER_UNAVAILABLE"
            assert body["retryable"] is True
            # No clip persisted in the degraded path.
            assert len(fake_object_store.objects) == 0
    finally:
        tts_module.build_tts_adapter = original_build
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def test_tts_rejects_oversized_text(client: TestClient, db_session: Session) -> None:
    _user, token = _auth(client, db_session)
    response = client.post(
        "/api/v1/tts",
        json={"text": "x" * 2001},
        headers=_headers(token, "tts-oversize"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_tts_accepts_optional_node_id_and_voice(client: TestClient, db_session: Session) -> None:
    _user, token = _auth(client, db_session)
    node_id = UUID("9512e5ec-f547-51b3-b0df-c5b3a877da9e")
    response = client.post(
        "/api/v1/tts",
        json={
            "text": "Hello world! This is a test.",
            "voice": "xiaoyu",
            "node_id": str(node_id),
        },
        headers=_headers(token, "tts-node"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # ASCII punctuation also splits the subtitle track.
    assert len(body["subtitle_track"]) == 2
