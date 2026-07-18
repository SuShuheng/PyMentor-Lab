"""Encrypted Provider configuration domain for BE-010."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from sqlalchemy import select, update
from sqlalchemy.orm import Session

_CIPHER_PREFIX = b"PM1"
_NONCE_BYTES = 12
_TAG_BYTES = 16


class ProviderType(StrEnum):
    LLM = "LLM"
    TTS = "TTS"
    ASR = "ASR"
    IMAGE = "IMAGE"
    OCR = "OCR"
    MODERATION = "MODERATION"
    EMBEDDING = "EMBEDDING"


class ProviderSecretError(ValueError):
    """A Provider master key or encrypted secret is invalid."""


@dataclass(frozen=True, slots=True)
class ResolvedProvider:
    id: UUID
    tenant_id: UUID
    provider_type: ProviderType
    vendor: str
    model: str
    api_key: str
    endpoint: str | None
    params: dict[str, object]


def decode_provider_master_key(encoded: str) -> bytes:
    """Decode the required URL-safe base64 AES-256 key."""
    if not encoded:
        raise ProviderSecretError("provider master key is not configured")
    try:
        key = base64.b64decode(encoded.encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as error:
        raise ProviderSecretError("provider master key must be valid base64") from error
    if len(key) != 32:
        raise ProviderSecretError("provider master key must decode to 32 bytes")
    return key


def provider_secret_context(tenant_id: UUID, provider_id: UUID) -> bytes:
    return f"provider-config:v1:{tenant_id}:{provider_id}".encode()


def encrypt_provider_secret(secret: str, master_key: bytes, context: bytes) -> bytes:
    if len(master_key) != 32:
        raise ProviderSecretError("provider master key must be 32 bytes")
    if not secret:
        raise ProviderSecretError("provider API key cannot be empty")
    cipher = AES.new(
        master_key,
        AES.MODE_GCM,
        nonce=get_random_bytes(_NONCE_BYTES),
        mac_len=_TAG_BYTES,
    )
    cipher.update(context)
    ciphertext, tag = cipher.encrypt_and_digest(secret.encode())
    return _CIPHER_PREFIX + cipher.nonce + tag + ciphertext


def decrypt_provider_secret(payload: bytes, master_key: bytes, context: bytes) -> str:
    if len(master_key) != 32:
        raise ProviderSecretError("provider master key must be 32 bytes")
    header_size = len(_CIPHER_PREFIX) + _NONCE_BYTES + _TAG_BYTES
    if len(payload) <= header_size or not payload.startswith(_CIPHER_PREFIX):
        raise ProviderSecretError("provider secret payload is invalid")
    nonce_start = len(_CIPHER_PREFIX)
    tag_start = nonce_start + _NONCE_BYTES
    cipher = AES.new(
        master_key,
        AES.MODE_GCM,
        nonce=payload[nonce_start:tag_start],
        mac_len=_TAG_BYTES,
    )
    cipher.update(context)
    try:
        plaintext = cipher.decrypt_and_verify(
            payload[tag_start + _TAG_BYTES :], payload[tag_start : tag_start + _TAG_BYTES]
        )
        return plaintext.decode()
    except (ValueError, UnicodeDecodeError) as error:
        raise ProviderSecretError("provider secret authentication failed") from error


def mask_provider_secret(secret: str) -> str:
    return f"********{secret[-4:]}"


def disable_other_providers(
    db: Session,
    *,
    tenant_id: UUID,
    provider_type: ProviderType,
    except_id: UUID,
) -> None:
    from app.models.provider import ProviderConfig

    # When the selected row is already tracked as enabled, an autoflush here
    # would violate the partial unique index before the previous row is disabled.
    with db.no_autoflush:
        db.execute(
            update(ProviderConfig)
            .where(
                ProviderConfig.tenant_id == tenant_id,
                ProviderConfig.provider_type == provider_type,
                ProviderConfig.id != except_id,
                ProviderConfig.enabled.is_(True),
            )
            .values(enabled=False, version=ProviderConfig.version + 1)
        )
    db.flush()


def resolve_enabled_provider(
    db: Session,
    *,
    tenant_id: UUID,
    provider_type: ProviderType,
    master_key: bytes,
) -> ResolvedProvider | None:
    """Resolve fresh state for a newly started job; no process-local cache is used."""
    from app.models.provider import ProviderConfig

    config = db.scalar(
        select(ProviderConfig).where(
            ProviderConfig.tenant_id == tenant_id,
            ProviderConfig.provider_type == provider_type,
            ProviderConfig.enabled.is_(True),
        )
    )
    if config is None:
        return None
    api_key = decrypt_provider_secret(
        config.api_key_encrypted,
        master_key,
        provider_secret_context(config.tenant_id, config.id),
    )
    return ResolvedProvider(
        id=config.id,
        tenant_id=config.tenant_id,
        provider_type=config.provider_type,
        vendor=config.vendor,
        model=config.model,
        api_key=api_key,
        endpoint=config.endpoint,
        params=config.params,
    )
