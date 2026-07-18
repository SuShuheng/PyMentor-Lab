"""BE-010 encrypted, tenant-scoped Provider configuration tests."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.providers import ProviderProbe, get_provider_probe
from app.db import get_db
from app.main import create_app
from app.models import AuditEvent, ProviderConfig, RoleName, Tenant, User, UserStatus
from app.providers import (
    ProviderSecretError,
    ProviderType,
    decrypt_provider_secret,
    encrypt_provider_secret,
    provider_secret_context,
    resolve_enabled_provider,
)
from app.security import create_access_token
from app.services import assign_role, get_or_create_tenant

MASTER_KEY = bytes(range(32))
MASTER_KEY_B64 = base64.urlsafe_b64encode(MASTER_KEY).decode("ascii")


@dataclass(slots=True)
class ProviderContext:
    system_admin: User
    course_admin: User
    system_token: str
    course_token: str


@pytest.fixture()
def provider_context(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> ProviderContext:
    monkeypatch.setenv("PYMENTOR_PROVIDER_MASTER_KEY", MASTER_KEY_B64)
    tenant = get_or_create_tenant(db_session, slug="default", name="Default Tenant")
    system_admin = _make_admin(db_session, tenant, RoleName.SYSTEM_ADMIN)
    course_admin = _make_admin(db_session, tenant, RoleName.COURSE_ADMIN)
    system_token, _, _ = create_access_token(
        user_id=str(system_admin.id),
        tenant_id=str(tenant.id),
        roles=[RoleName.SYSTEM_ADMIN.value],
    )
    course_token, _, _ = create_access_token(
        user_id=str(course_admin.id),
        tenant_id=str(tenant.id),
        roles=[RoleName.COURSE_ADMIN.value],
    )
    return ProviderContext(system_admin, course_admin, system_token, course_token)


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _make_admin(db: Session, tenant: Tenant, role: RoleName) -> User:
    user = User(
        tenant_id=tenant.id,
        email=f"{role.value.lower()}-{uuid4().hex}@example.com",
        password_hash="not-used-by-token-tests",
        status=UserStatus.ACTIVE,
        display_name=role.value,
    )
    db.add(user)
    db.flush()
    assign_role(db, user_id=user.id, role_name=role.value)
    return user


def _headers(token: str, *, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _body(
    *,
    provider_type: str = "LLM",
    model: str = "spark-v4",
    api_key: str = "provider-secret-value",
    enabled: bool = True,
) -> dict[str, object]:
    return {
        "provider_type": provider_type,
        "vendor": "xfyun",
        "model": model,
        "api_key": api_key,
        "endpoint": "https://provider.example.com/v1/models",
        "params": {"temperature": 0.2},
        "enabled": enabled,
    }


def _create_provider(
    client: TestClient,
    context: ProviderContext,
    *,
    body: dict[str, object] | None = None,
    key: str | None = None,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/admin/providers",
        json=body or _body(),
        headers=_headers(context.system_token, key=key or f"provider-{uuid4().hex}"),
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert isinstance(result, dict)
    return result


def test_only_system_admin_can_create_list_and_secret_is_encrypted_and_masked(
    client: TestClient, db_session: Session, provider_context: ProviderContext
) -> None:
    denied = client.get("/api/v1/admin/providers", headers=_headers(provider_context.course_token))
    missing_idempotency = client.post(
        "/api/v1/admin/providers",
        json=_body(),
        headers=_headers(provider_context.system_token),
    )
    key = f"provider-{uuid4().hex}"
    created = _create_provider(client, provider_context, key=key)
    replay = client.post(
        "/api/v1/admin/providers",
        json=_body(),
        headers=_headers(provider_context.system_token, key=key),
    )

    assert denied.status_code == 403
    assert missing_idempotency.status_code == 422
    assert replay.status_code == 201
    assert replay.json() == created
    assert "provider-secret-value" not in str(created)
    assert created["api_key_masked"] == "********alue"

    row = db_session.get(ProviderConfig, created["id"])
    assert row is not None
    assert b"provider-secret-value" not in row.api_key_encrypted
    context = provider_secret_context(row.tenant_id, row.id)
    assert decrypt_provider_secret(row.api_key_encrypted, MASTER_KEY, context) == (
        "provider-secret-value"
    )

    foreign_tenant = Tenant(slug=f"provider-foreign-{uuid4().hex}", name="Foreign")
    db_session.add(foreign_tenant)
    db_session.flush()
    foreign_id = uuid4()
    db_session.add(
        ProviderConfig(
            id=foreign_id,
            tenant_id=foreign_tenant.id,
            provider_type=ProviderType.LLM,
            vendor="foreign",
            model="foreign-model",
            api_key_encrypted=encrypt_provider_secret(
                "foreign-provider-key",
                MASTER_KEY,
                provider_secret_context(foreign_tenant.id, foreign_id),
            ),
            endpoint=None,
            params={},
            enabled=True,
        )
    )
    db_session.flush()

    listed = client.get("/api/v1/admin/providers", headers=_headers(provider_context.system_token))
    foreign_patch = client.patch(
        f"/api/v1/admin/providers/{foreign_id}",
        json={"enabled": False},
        headers=_headers(provider_context.system_token, key=f"provider-foreign-{uuid4().hex}"),
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == [created]
    assert "api_key" not in listed.text.replace("api_key_masked", "")
    assert foreign_patch.status_code == 404


def test_enabling_provider_switches_new_resolution_and_audits_changes(
    client: TestClient, db_session: Session, provider_context: ProviderContext
) -> None:
    first = _create_provider(client, provider_context)
    second = _create_provider(
        client,
        provider_context,
        body=_body(model="spark-lite", api_key="second-provider-key"),
    )

    first_row = db_session.get(ProviderConfig, first["id"])
    second_row = db_session.get(ProviderConfig, second["id"])
    assert first_row is not None and second_row is not None
    assert first_row.enabled is False
    assert second_row.enabled is True
    resolved = resolve_enabled_provider(
        db_session,
        tenant_id=provider_context.system_admin.tenant_id,
        provider_type=ProviderType.LLM,
        master_key=MASTER_KEY,
    )
    assert resolved is not None
    assert resolved.id == second_row.id
    assert resolved.api_key == "second-provider-key"

    patched = client.patch(
        f"/api/v1/admin/providers/{first_row.id}",
        json={"api_key": "rotated-provider-key", "enabled": True},
        headers=_headers(provider_context.system_token, key=f"provider-patch-{uuid4().hex}"),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["api_key_masked"] == "********-key"
    db_session.refresh(first_row)
    db_session.refresh(second_row)
    assert first_row.enabled is True
    assert second_row.enabled is False

    actions = set(
        db_session.scalars(
            select(AuditEvent.action).where(
                AuditEvent.tenant_id == provider_context.system_admin.tenant_id,
                AuditEvent.resource_type == "provider_config",
            )
        )
    )
    assert {"PROVIDER_CONFIG_CREATED", "PROVIDER_CONFIG_UPDATED"} <= actions


def test_provider_connectivity_uses_decrypted_key_without_returning_it(
    client: TestClient,
    provider_context: ProviderContext,
) -> None:
    created = _create_provider(client, provider_context)
    observed: dict[str, str] = {}

    def _probe(endpoint: str, api_key: str) -> ProviderProbe:
        observed.update(endpoint=endpoint, api_key=api_key)
        return ProviderProbe(ok=True, latency_ms=14, status_code=200, detail="reachable")

    cast(FastAPI, client.app).dependency_overrides[get_provider_probe] = lambda: _probe
    response = client.post(
        f"/api/v1/admin/providers/{created['id']}/test",
        headers=_headers(provider_context.system_token, key=f"provider-test-{uuid4().hex}"),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "ok": True,
        "latency_ms": 14,
        "status_code": 200,
        "detail": "reachable",
    }
    assert observed == {
        "endpoint": "https://provider.example.com/v1/models",
        "api_key": "provider-secret-value",
    }
    assert "provider-secret-value" not in response.text


def test_provider_params_cannot_hide_secrets(
    client: TestClient, provider_context: ProviderContext
) -> None:
    body = _body()
    body["params"] = {"nested": {"access_token": "must-not-be-persisted"}}

    response = client.post(
        "/api/v1/admin/providers",
        json=body,
        headers=_headers(provider_context.system_token, key=f"provider-invalid-{uuid4().hex}"),
    )

    assert response.status_code == 422
    assert "must-not-be-persisted" not in response.text


def test_provider_cipher_rejects_tampering() -> None:
    context = b"provider:test"
    encrypted = encrypt_provider_secret("provider-secret-value", MASTER_KEY, context)
    assert decrypt_provider_secret(encrypted, MASTER_KEY, context) == "provider-secret-value"
    tampered = encrypted[:-1] + bytes([encrypted[-1] ^ 1])

    with pytest.raises(ProviderSecretError):
        decrypt_provider_secret(tampered, MASTER_KEY, context)
