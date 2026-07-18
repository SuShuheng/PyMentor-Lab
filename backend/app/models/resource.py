"""Normalized BE-007 resource job, artifact, object, and review records."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import Enum as SqlEnum
from sqlalchemy.types import Uuid

from app.db import Base
from app.resources import ResourceArtifactStatus, ResourceGate, ResourceJobStatus, ResourceType


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ResourceJobRecord(Base):
    __tablename__ = "resource_jobs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_resource_jobs_tenant_idempotency",
        ),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_resource_jobs_progress_range",
        ),
        ForeignKeyConstraint(
            ["node_id", "course_id"],
            ["knowledge_nodes.id", "knowledge_nodes.course_id"],
            name="fk_resource_jobs_course_node",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    node_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ResourceJobStatus] = mapped_column(
        SqlEnum(ResourceJobStatus, native_enum=False, length=32),
        default=ResourceJobStatus.QUEUED,
        nullable=False,
        index=True,
    )
    requested_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    context_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    progress_percent: Mapped[int] = mapped_column(default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class LearningResourceRecord(Base):
    __tablename__ = "learning_resources"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "resource_type",
            "version",
            name="uq_learning_resources_job_type_version",
        ),
        CheckConstraint("version >= 1", name="ck_learning_resources_version_positive"),
    )

    id: Mapped[UUID] = _uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("resource_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_type: Mapped[ResourceType] = mapped_column(
        SqlEnum(ResourceType, native_enum=False, length=32), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[ResourceArtifactStatus] = mapped_column(
        SqlEnum(ResourceArtifactStatus, native_enum=False, length=16),
        default=ResourceArtifactStatus.STAGED,
        nullable=False,
        index=True,
    )
    source_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    context_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class ResourceObjectRecord(Base):
    __tablename__ = "resource_objects"
    __table_args__ = (
        UniqueConstraint("object_key", name="uq_resource_objects_key"),
        UniqueConstraint(
            "resource_id", "version", name="uq_resource_objects_resource_version"
        ),
        CheckConstraint("version >= 1", name="ck_resource_objects_version_positive"),
        CheckConstraint("size_bytes >= 0", name="ck_resource_objects_size_nonnegative"),
    )

    id: Mapped[UUID] = _uuid_pk()
    resource_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("learning_resources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = _created_at()


class ResourceReviewRecord(Base):
    __tablename__ = "resource_reviews"
    __table_args__ = (
        UniqueConstraint(
            "resource_id",
            "gate",
            "version",
            name="uq_resource_reviews_resource_gate_version",
        ),
        CheckConstraint("version >= 1", name="ck_resource_reviews_version_positive"),
    )

    id: Mapped[UUID] = _uuid_pk()
    resource_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("learning_resources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gate: Mapped[ResourceGate] = mapped_column(
        SqlEnum(ResourceGate, native_enum=False, length=16), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    findings: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    reviewer: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = _created_at()
