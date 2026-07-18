"""Unit tests for the no-shell, digest-gated PostgreSQL maintenance adapter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.maintenance import (
    DatabaseMaintenanceError,
    PostgresDatabaseMaintenance,
    _postgres_environment,
    _run_tool,
)


class FakeObjectClient:
    def __init__(self, download: bytes = b"") -> None:
        self.download = download
        self.upload: tuple[str, str, str, dict[str, str]] | None = None

    def fget_object(self, bucket: str, key: str, filename: str) -> None:
        Path(filename).write_bytes(self.download)

    def fput_object(
        self,
        bucket: str,
        key: str,
        filename: str,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        self.upload = (bucket, key, content_type, metadata)


def _adapter(client: FakeObjectClient) -> PostgresDatabaseMaintenance:
    adapter = PostgresDatabaseMaintenance.__new__(PostgresDatabaseMaintenance)
    adapter.settings = Settings(
        database_url="postgresql+psycopg://operator:super-secret@db.internal:5432/course"
    )
    adapter.object_settings = SimpleNamespace(bucket="private-backups")
    adapter.client = client
    return adapter


def test_postgres_environment_keeps_password_out_of_database_arguments() -> None:
    environment = _postgres_environment(
        "postgresql+psycopg://operator:super-secret@db.internal:5432/course"
    )
    assert environment["PGPASSWORD"] == "super-secret"
    assert environment["PGHOST"] == "db.internal"
    assert environment["PGDATABASE"] == "course"
    connection_fields = " ".join(
        environment[key] for key in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE")
    )
    assert "postgresql" not in connection_fields
    assert "super-secret" not in connection_fields


def test_run_tool_uses_argument_vector_without_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_run(arguments: list[str], **kwargs: Any) -> None:
        captured["arguments"] = arguments
        captured.update(kwargs)

    monkeypatch.setattr("app.maintenance.shutil.which", lambda _name: "/usr/bin/pg_dump")
    monkeypatch.setattr("app.maintenance.subprocess.run", _fake_run)
    _run_tool(["pg_dump", "--format=custom"], environment={"PGPASSWORD": "secret"}, timeout=5)

    assert captured["arguments"] == ["/usr/bin/pg_dump", "--format=custom"]
    assert captured["shell"] is False
    assert "secret" not in " ".join(captured["arguments"])
    assert captured["stdin"] is not None
    assert captured["stdout"] is not None
    assert captured["stderr"] is not None


def test_restore_rejects_digest_mismatch_before_pg_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter(FakeObjectClient(b"tampered archive"))
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "app.maintenance._run_tool",
        lambda arguments, **_kwargs: calls.append(arguments),
    )

    with pytest.raises(DatabaseMaintenanceError, match="digest verification failed"):
        adapter.restore_backup(
            object_key="system-backups/known.dump",
            expected_digest="a" * 64,
        )

    assert calls == []


def test_restore_rejects_object_outside_governed_prefix() -> None:
    adapter = _adapter(FakeObjectClient(b"archive"))
    with pytest.raises(DatabaseMaintenanceError, match="governed prefix"):
        adapter.restore_backup(object_key="resources/not-a-backup", expected_digest="a" * 64)
