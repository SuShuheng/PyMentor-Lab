"""Safe PostgreSQL archive execution behind an injectable maintenance port."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from minio import Minio
from minio.versioningconfig import VersioningConfig
from sqlalchemy.engine import make_url

from app.config import Settings, get_settings
from app.object_store import MinioObjectStoreSettings


class DatabaseMaintenanceError(RuntimeError):
    """A backup or atomic restore could not be completed safely."""


@dataclass(frozen=True, slots=True)
class BackupArtifact:
    object_key: str
    digest: str
    size_bytes: int


class DatabaseMaintenance(Protocol):
    requires_released_transaction: bool

    def create_backup(self, backup_id: UUID) -> BackupArtifact: ...

    def restore_backup(self, *, object_key: str, expected_digest: str) -> None: ...


def _postgres_environment(database_url: str) -> dict[str, str]:
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql") or not url.database:
        raise DatabaseMaintenanceError("PostgreSQL maintenance is unavailable")
    environment = os.environ.copy()
    environment.update(
        {
            "PGDATABASE": url.database,
            "PGCONNECT_TIMEOUT": "5",
            "PGOPTIONS": "-c statement_timeout=60000 -c lock_timeout=10000",
        }
    )
    if url.host:
        environment["PGHOST"] = url.host
    if url.port:
        environment["PGPORT"] = str(url.port)
    if url.username:
        environment["PGUSER"] = url.username
    if url.password:
        environment["PGPASSWORD"] = url.password
    return environment


def _run_tool(arguments: list[str], *, environment: dict[str, str], timeout: int) -> None:
    executable = shutil.which(arguments[0])
    if executable is None:
        raise DatabaseMaintenanceError("PostgreSQL maintenance tooling is unavailable")
    try:
        subprocess.run(
            [executable, *arguments[1:]],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DatabaseMaintenanceError("PostgreSQL maintenance command failed") from error


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PostgresDatabaseMaintenance:
    """Create private custom-format archives and restore them atomically.

    Restore first checks the archive table-of-contents and digest. The live restore
    uses pg_restore's single-transaction mode, so any command failure rolls back
    the whole restore instead of leaving a partially replaced schema.
    """

    requires_released_transaction = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        object_settings = MinioObjectStoreSettings.from_application_settings(settings)
        self.object_settings = object_settings
        self.client = Minio(
            object_settings.endpoint,
            access_key=object_settings.access_key,
            secret_key=object_settings.secret_key,
            secure=object_settings.secure,
        )
        if not self.client.bucket_exists(object_settings.bucket):
            self.client.make_bucket(object_settings.bucket)
        self.client.set_bucket_versioning(object_settings.bucket, VersioningConfig("Enabled"))

    def create_backup(self, backup_id: UUID) -> BackupArtifact:
        key = f"system-backups/{backup_id}.dump"
        environment = _postgres_environment(self.settings.database_url)
        with tempfile.TemporaryDirectory(prefix="pymentor-backup-") as directory:
            archive = Path(directory) / "database.dump"
            _run_tool(
                [
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    "--file",
                    str(archive),
                ],
                environment=environment,
                timeout=600,
            )
            digest = _file_digest(archive)
            size_bytes = archive.stat().st_size
            self.client.fput_object(
                self.object_settings.bucket,
                key,
                str(archive),
                content_type="application/vnd.postgresql.custom-dump",
                metadata={"sha256": digest, "backup-format": "pg-custom-v1"},
            )
        return BackupArtifact(key, digest, size_bytes)

    def restore_backup(self, *, object_key: str, expected_digest: str) -> None:
        if not object_key.startswith("system-backups/") or ".." in object_key.split("/"):
            raise DatabaseMaintenanceError("Backup object is outside the governed prefix")
        environment = _postgres_environment(self.settings.database_url)
        with tempfile.TemporaryDirectory(prefix="pymentor-restore-") as directory:
            archive = Path(directory) / "database.dump"
            try:
                self.client.fget_object(
                    self.object_settings.bucket,
                    object_key,
                    str(archive),
                )
            except Exception as error:
                raise DatabaseMaintenanceError("Backup archive is unavailable") from error
            actual_digest = _file_digest(archive)
            if actual_digest != expected_digest:
                raise DatabaseMaintenanceError("Backup archive digest verification failed")
            _run_tool(
                ["pg_restore", "--list", str(archive)],
                environment=environment,
                timeout=60,
            )
            _run_tool(
                [
                    "pg_restore",
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--no-privileges",
                    "--single-transaction",
                    "--exit-on-error",
                    "--dbname",
                    environment["PGDATABASE"],
                    str(archive),
                ],
                environment=environment,
                timeout=600,
            )


def build_database_maintenance() -> DatabaseMaintenance:
    return PostgresDatabaseMaintenance(get_settings())
