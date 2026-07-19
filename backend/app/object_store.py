"""Private, versioned MinIO object storage with streaming SHA-256 verification."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from minio import Minio
from minio.versioningconfig import VersioningConfig

from app.config import Settings
from app.resources import ResourceGateError, StoredObject

_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


@dataclass(frozen=True, slots=True)
class MinioObjectStoreSettings:
    endpoint: str
    access_key: str
    secret_key: str = field(repr=False)
    bucket: str = "pymentor-resources"
    secure: bool = True

    def __post_init__(self) -> None:
        if (
            not self.endpoint
            or "://" in self.endpoint
            or "/" in self.endpoint
            or "@" in self.endpoint
        ):
            raise ValueError("MinIO endpoint must be host[:port] without credentials or scheme")
        if not self.access_key or not self.secret_key:
            raise ValueError("MinIO credentials must not be empty")
        if not _BUCKET.fullmatch(self.bucket):
            raise ValueError("MinIO bucket must be a valid lowercase S3 bucket name")

    @classmethod
    def from_application_settings(cls, settings: Settings) -> MinioObjectStoreSettings:
        return cls(
            endpoint=settings.object_store_endpoint,
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
            bucket=settings.object_store_bucket,
            secure=settings.object_store_secure,
        )


class MinioObjectStore:
    """Object-store port; bucket remains private and DB state governs access."""

    def __init__(self, settings: MinioObjectStoreSettings, *, client: Any | None = None) -> None:
        self.settings = settings
        self.client = client or Minio(
            settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
            secure=settings.secure,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.settings.bucket):
            self.client.make_bucket(self.settings.bucket)
        self.client.set_bucket_versioning(
            self.settings.bucket,
            VersioningConfig("Enabled"),
        )

    def put(self, *, key: str, content: bytes, mime_type: str, version: int) -> StoredObject:
        if not key.startswith("resources/") or ".." in key.split("/"):
            raise ResourceGateError("object key is outside the governed resources prefix")
        if version < 1:
            raise ResourceGateError("object version must be positive")
        digest = hashlib.sha256(content).hexdigest()
        self.client.put_object(
            self.settings.bucket,
            key,
            BytesIO(content),
            len(content),
            content_type=mime_type,
            metadata={"sha256": digest, "resource-version": str(version)},
        )
        return StoredObject(
            key=key,
            version=version,
            digest=digest,
            mime_type=mime_type,
            size_bytes=len(content),
        )

    def verify(self, key: str, expected_digest: str) -> bool:
        response = self.client.get_object(self.settings.bucket, key)
        digest = hashlib.sha256()
        try:
            for chunk in response.stream(amt=64 * 1024):
                digest.update(chunk)
        finally:
            response.close()
            response.release_conn()
        return digest.hexdigest() == expected_digest

    def publish(self, key: str, expected_digest: str) -> None:
        if not self.verify(key, expected_digest):
            raise ResourceGateError("resource object digest verification failed")

    def read_published(self, key: str, expected_digest: str, *, max_bytes: int) -> bytes:
        if not key.startswith("resources/") or ".." in key.split("/"):
            raise ResourceGateError("object key is outside the governed resources prefix")
        response = self.client.get_object(self.settings.bucket, key)
        digest = hashlib.sha256()
        content = bytearray()
        try:
            for chunk in response.stream(amt=64 * 1024):
                content.extend(chunk)
                digest.update(chunk)
                if len(content) > max_bytes:
                    raise ResourceGateError("resource object exceeds the download boundary")
        finally:
            response.close()
            response.release_conn()
        if digest.hexdigest() != expected_digest:
            raise ResourceGateError("resource object digest verification failed")
        return bytes(content)
