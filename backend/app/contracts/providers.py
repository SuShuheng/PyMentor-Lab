"""Strict contracts for System Admin Provider configuration."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)

from app.providers import ProviderType

_SENSITIVE_PARAM_KEY = re.compile(
    r"(?:api[_-]?key|secret|password|authorization|cookie|token|credential)", re.IGNORECASE
)


def _contains_sensitive_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            _SENSITIVE_PARAM_KEY.search(str(key)) or _contains_sensitive_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _validate_params(value: dict[str, Any]) -> dict[str, Any]:
    if _contains_sensitive_key(value):
        raise ValueError("provider params cannot contain secret-like fields")
    if len(json.dumps(value, ensure_ascii=False, default=str).encode()) > 16_384:
        raise ValueError("provider params exceed 16 KiB")
    return value


def _validate_endpoint(value: HttpUrl | None) -> HttpUrl | None:
    if value is None:
        return None
    loopback = value.host in {"127.0.0.1", "localhost", "::1"}
    if value.scheme != "https" and not (value.scheme == "http" and loopback):
        raise ValueError("provider endpoint must use HTTPS (loopback HTTP is allowed)")
    if value.username is not None or value.password is not None:
        raise ValueError("provider endpoint cannot contain embedded credentials")
    return value


class StrictProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderConfigCreate(StrictProviderModel):
    provider_type: ProviderType
    vendor: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    model: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:/-]+$")
    api_key: SecretStr = Field(min_length=8, max_length=4096)
    endpoint: HttpUrl | None
    params: dict[str, Any]
    enabled: bool

    _params_are_safe = field_validator("params")(_validate_params)
    _endpoint_is_safe = field_validator("endpoint")(_validate_endpoint)


class ProviderConfigUpdate(StrictProviderModel):
    vendor: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$"
    )
    model: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:/-]+$"
    )
    api_key: SecretStr | None = Field(default=None, min_length=8, max_length=4096)
    endpoint: HttpUrl | None = None
    params: dict[str, Any] | None = None
    enabled: bool | None = None

    @field_validator("params")
    @classmethod
    def _optional_params_are_safe(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if value is None else _validate_params(value)

    _endpoint_is_safe = field_validator("endpoint")(_validate_endpoint)

    @model_validator(mode="after")
    def _has_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one Provider field must be supplied")
        return self


class ProviderConfigView(StrictProviderModel):
    id: UUID
    provider_type: ProviderType
    vendor: str
    model: str
    api_key_masked: str
    endpoint: str | None
    params: dict[str, Any]
    enabled: bool
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class ProviderConfigPage(StrictProviderModel):
    items: list[ProviderConfigView]


class ProviderConnectivityTestRequest(StrictProviderModel):
    """Optional request body for ``POST /{id}/test`` (BE-019).

    When ``api_key`` is supplied it is used INSTEAD of the stored key for the
    one-shot reachability probe (pre-save rotation validation). It is never
    persisted and never echoed in the response. Omit the body to test the
    currently stored key.
    """

    api_key: SecretStr | None = Field(default=None, min_length=8, max_length=4096)


class ProviderConnectivityView(StrictProviderModel):
    """Standardized connection-test response (BE-019).

    The legacy ``status_code``/``detail`` pair is preserved for diagnostics
    and backwards compatibility, while the new ``model_id``/``error_code``
    pair gives the UI a machine-readable contract. ``error_code`` is ``None``
    on success; on failure it carries a stable enum-like string
    (``CONNECTIVITY_FAILED``). The API key is never echoed.
    """

    ok: bool
    latency_ms: int = Field(ge=0)
    status_code: int | None
    detail: str = Field(min_length=1, max_length=128)
    model_id: str | None = Field(default=None, max_length=128)
    error_code: str | None = Field(default=None, max_length=64)
