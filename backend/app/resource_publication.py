"""PostgreSQL-backed BE-007 artifact staging, review, and publication."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    LearningResourceRecord,
    ResourceJobRecord,
    ResourceObjectRecord,
    ResourceReviewRecord,
)
from app.resources import (
    ResourceArtifactStatus,
    ResourceGate,
    ResourceGateError,
    ResourceJobStatus,
    ResourceType,
    StoredObject,
)


class ObjectStorePort(Protocol):
    def put(self, *, key: str, content: bytes, mime_type: str, version: int) -> StoredObject: ...

    def verify(self, key: str, expected_digest: str) -> bool: ...

    def publish(self, key: str, expected_digest: str) -> None: ...


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class SqlResourcePublicationService:
    """Formal-state coordinator; the Worker cannot publish objects directly."""

    def __init__(self, db: Session, object_store: ObjectStorePort) -> None:
        self.db = db
        self.object_store = object_store

    def _job(self, job_id: UUID) -> ResourceJobRecord:
        job = self.db.scalar(
            select(ResourceJobRecord)
            .where(ResourceJobRecord.id == job_id)
            .with_for_update()
        )
        if job is None:
            raise LookupError("resource job not found")
        return job

    def _resource(self, resource_id: UUID) -> tuple[LearningResourceRecord, ResourceJobRecord]:
        resource = self.db.scalar(
            select(LearningResourceRecord)
            .where(LearningResourceRecord.id == resource_id)
            .with_for_update()
        )
        if resource is None:
            raise LookupError("learning resource not found")
        return resource, self._job(resource.job_id)

    def _object(self, resource_id: UUID) -> ResourceObjectRecord:
        stored = self.db.scalar(
            select(ResourceObjectRecord).where(ResourceObjectRecord.resource_id == resource_id)
        )
        if stored is None:
            raise ResourceGateError("resource object metadata not found")
        return stored

    def stage(
        self,
        *,
        job_id: UUID,
        resource_type: ResourceType,
        content: bytes,
        mime_type: str,
        source_ids: tuple[UUID, ...],
    ) -> LearningResourceRecord:
        job = self._job(job_id)
        if resource_type.value not in job.requested_types:
            raise ResourceGateError("resource type was not requested by this job")
        if not source_ids or not {str(item) for item in source_ids}.issubset(set(job.source_ids)):
            raise ResourceGateError("resource artifact requires an approved source")
        if not content:
            raise ResourceGateError("resource artifact content must not be empty")
        if not mime_type or len(mime_type) > 128:
            raise ResourceGateError("resource artifact MIME type is invalid")

        previous = self.db.scalar(
            select(LearningResourceRecord)
            .where(
                LearningResourceRecord.job_id == job.id,
                LearningResourceRecord.resource_type == resource_type,
            )
            .order_by(LearningResourceRecord.version.desc())
            .limit(1)
        )
        if previous is not None and previous.status is not ResourceArtifactStatus.REJECTED:
            raise ResourceGateError("resource type already has an active artifact")
        version = 1 if previous is None else previous.version + 1
        resource_id = uuid4()
        content_digest = _digest(content)
        slug = resource_type.value.lower().replace("_", "-")
        key = f"resources/{job.tenant_id}/{job.id}/{slug}/v{version}/{content_digest}"
        stored = self.object_store.put(
            key=key,
            content=content,
            mime_type=mime_type,
            version=version,
        )
        if stored.digest != content_digest or stored.size_bytes != len(content):
            raise ResourceGateError("object store metadata does not match the staged content")

        resource = LearningResourceRecord(
            id=resource_id,
            tenant_id=job.tenant_id,
            job_id=job.id,
            resource_type=resource_type,
            version=version,
            status=ResourceArtifactStatus.STAGED,
            source_ids=[str(item) for item in source_ids],
            context_digest=job.context_digest,
            content_digest=content_digest,
            metadata_json={},
        )
        self.db.add(resource)
        self.db.flush()
        self.db.add(
            ResourceObjectRecord(
                resource_id=resource.id,
                object_key=stored.key,
                digest=stored.digest,
                mime_type=stored.mime_type,
                size_bytes=stored.size_bytes,
                version=stored.version,
                published=False,
            )
        )
        job.status = ResourceJobStatus.REVIEWING
        job.error_code = None
        self.db.flush()
        return resource

    def review(
        self,
        *,
        resource_id: UUID,
        gate: ResourceGate,
        passed: bool,
        findings: tuple[str, ...],
        reviewer: str,
    ) -> ResourceReviewRecord:
        resource, job = self._resource(resource_id)
        if resource.status in {
            ResourceArtifactStatus.PUBLISHED,
            ResourceArtifactStatus.REJECTED,
        }:
            raise ResourceGateError("resource artifact is already terminal")
        if not reviewer or len(reviewer) > 128:
            raise ResourceGateError("resource reviewer identity is invalid")
        stored = self._object(resource.id)
        if not self.object_store.verify(stored.object_key, stored.digest):
            resource.status = ResourceArtifactStatus.REJECTED
            job.status = ResourceJobStatus.FAILED_RETRYABLE
            job.error_code = "OBJECT_DIGEST_MISMATCH"
            self.db.flush()
            raise ResourceGateError("resource object digest verification failed")

        version = (
            self.db.scalar(
                select(func.max(ResourceReviewRecord.version)).where(
                    ResourceReviewRecord.resource_id == resource.id,
                    ResourceReviewRecord.gate == gate,
                )
            )
            or 0
        ) + 1
        review = ResourceReviewRecord(
            resource_id=resource.id,
            gate=gate,
            version=version,
            passed=passed,
            findings=list(findings),
            reviewer=reviewer,
        )
        self.db.add(review)
        resource.status = (
            ResourceArtifactStatus.REVIEWING if passed else ResourceArtifactStatus.REJECTED
        )
        job.status = (
            ResourceJobStatus.REVIEWING
            if passed
            else (
                ResourceJobStatus.FAILED_FINAL
                if gate is ResourceGate.COMPLIANCE
                else ResourceJobStatus.FAILED_RETRYABLE
            )
        )
        job.error_code = None if passed else "REVIEW_GATE_FAILED"
        self.db.flush()
        return review

    def publish(self, *, resource_id: UUID) -> LearningResourceRecord:
        resource, job = self._resource(resource_id)
        reviews = list(
            self.db.scalars(
                select(ResourceReviewRecord)
                .where(ResourceReviewRecord.resource_id == resource.id)
                .order_by(ResourceReviewRecord.gate, ResourceReviewRecord.version.desc())
            )
        )
        latest: dict[ResourceGate, ResourceReviewRecord] = {}
        for review in reviews:
            latest.setdefault(review.gate, review)
        if any(gate not in latest or not latest[gate].passed for gate in ResourceGate):
            if any(review.passed is False for review in latest.values()):
                resource.status = ResourceArtifactStatus.REJECTED
            self.db.flush()
            raise ResourceGateError("resource must pass both review gates before publication")

        stored = self._object(resource.id)
        if not self.object_store.verify(stored.object_key, stored.digest):
            resource.status = ResourceArtifactStatus.REJECTED
            job.status = ResourceJobStatus.FAILED_RETRYABLE
            job.error_code = "OBJECT_DIGEST_MISMATCH"
            self.db.flush()
            raise ResourceGateError("resource object digest verification failed")
        self.object_store.publish(stored.object_key, stored.digest)
        stored.published = True
        resource.status = ResourceArtifactStatus.PUBLISHED
        resource.published_at = datetime.now(UTC)
        self.db.flush()

        published_count = self.db.scalar(
            select(func.count(func.distinct(LearningResourceRecord.resource_type))).where(
                LearningResourceRecord.job_id == job.id,
                LearningResourceRecord.status == ResourceArtifactStatus.PUBLISHED,
            )
        ) or 0
        job.progress_percent = published_count * 100 // len(job.requested_types)
        job.status = (
            ResourceJobStatus.READY
            if published_count == len(job.requested_types)
            else ResourceJobStatus.PARTIAL_READY
        )
        job.error_code = None
        self.db.flush()
        return resource
