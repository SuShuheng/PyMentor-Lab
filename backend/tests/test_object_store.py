"""BE-007 MinIO object-store adapter tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.object_store import MinioObjectStore, MinioObjectStoreSettings
from app.resources import ResourceGateError


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False
        self.released = False

    def stream(self, amt: int):
        for offset in range(0, len(self.content), amt):
            yield self.content[offset : offset + amt]

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


@dataclass
class FakePutResult:
    version_id: str = "version-id"


class FakeMinioClient:
    def __init__(self) -> None:
        self.bucket = False
        self.versioning = None
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}
        self.last_response: FakeResponse | None = None

    def bucket_exists(self, bucket: str) -> bool:
        assert bucket == "pymentor-resources"
        return self.bucket

    def make_bucket(self, bucket: str) -> None:
        assert bucket == "pymentor-resources"
        self.bucket = True

    def set_bucket_versioning(self, bucket: str, config: object) -> None:
        assert bucket == "pymentor-resources"
        self.versioning = config

    def put_object(
        self,
        bucket: str,
        key: str,
        data: object,
        length: int,
        content_type: str,
        metadata: dict[str, str],
    ) -> FakePutResult:
        assert bucket == "pymentor-resources"
        assert content_type == "text/plain"
        content = data.read(length)
        self.objects[key] = content
        self.metadata[key] = metadata
        return FakePutResult()

    def get_object(self, bucket: str, key: str) -> FakeResponse:
        assert bucket == "pymentor-resources"
        response = FakeResponse(self.objects[key])
        self.last_response = response
        return response


def _settings() -> MinioObjectStoreSettings:
    return MinioObjectStoreSettings(
        endpoint="127.0.0.1:9000",
        access_key="pymentor",
        secret_key="secret-minio-key",
        bucket="pymentor-resources",
        secure=False,
    )


def test_settings_hide_secret_and_reject_unsafe_values() -> None:
    assert "secret-minio-key" not in repr(_settings())
    with pytest.raises(ValueError, match="endpoint"):
        MinioObjectStoreSettings(
            endpoint="http://127.0.0.1:9000",
            access_key="pymentor",
            secret_key="secret",
            bucket="pymentor-resources",
            secure=False,
        )
    with pytest.raises(ValueError, match="bucket"):
        MinioObjectStoreSettings(
            endpoint="127.0.0.1:9000",
            access_key="pymentor",
            secret_key="secret",
            bucket="INVALID_BUCKET",
            secure=False,
        )


def test_put_verify_and_publish_use_versioned_private_bucket() -> None:
    client = FakeMinioClient()
    store = MinioObjectStore(_settings(), client=client)

    stored = store.put(
        key="resources/tenant/job/card/v1/digest",
        content=b"verified content",
        mime_type="text/plain",
        version=1,
    )

    assert client.bucket is True
    assert client.versioning is not None
    assert stored.version == 1
    assert client.metadata[stored.key] == {
        "sha256": stored.digest,
        "resource-version": "1",
    }
    assert store.verify(stored.key, stored.digest) is True
    assert client.last_response is not None
    assert client.last_response.closed is True
    assert client.last_response.released is True
    store.publish(stored.key, stored.digest)

    client.objects[stored.key] = b"tampered"
    assert store.verify(stored.key, stored.digest) is False
    with pytest.raises(ResourceGateError, match="digest"):
        store.publish(stored.key, stored.digest)
