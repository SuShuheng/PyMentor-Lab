"""PostgreSQL authority for BE-007 resource-job creation and query views."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.resources import (
    ResourceArtifactView,
    ResourceJobCreate,
    ResourceJobView,
    ResourceObjectView,
)
from app.models import (
    CourseCatalog,
    KnowledgeNode,
    LearningResourceRecord,
    ResourceJobRecord,
    ResourceObjectRecord,
)
from app.resources import ResourceJobConflict, ResourceJobStatus


class ResourceJobScopeError(LookupError):
    """The governed node or student-scoped job does not exist."""


def _canonical_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def resource_request_digest(
    body: ResourceJobCreate, *, tenant_id: UUID, student_id: UUID
) -> str:
    return _canonical_digest(
        {
            "tenant_id": str(tenant_id),
            "student_id": str(student_id),
            "course_id": str(body.course_id),
            "node_id": str(body.node_id),
            "resource_types": [item.value for item in body.resource_types],
        }
    )


def find_idempotent_resource_job(
    db: Session,
    *,
    tenant_id: UUID,
    idempotency_key: str,
) -> ResourceJobRecord | None:
    return db.scalar(
        select(ResourceJobRecord).where(
            ResourceJobRecord.tenant_id == tenant_id,
            ResourceJobRecord.idempotency_key == idempotency_key,
        )
    )


def assert_resource_job_replay(
    existing: ResourceJobRecord | None, *, expected_request_digest: str
) -> None:
    if existing is not None and existing.request_digest != expected_request_digest:
        raise ResourceJobConflict("idempotency key belongs to a different resource request")


def create_resource_job(
    db: Session,
    body: ResourceJobCreate,
    *,
    tenant_id: UUID,
    student_id: UUID,
    idempotency_key: str,
    request_digest: str,
) -> ResourceJobRecord:
    node = db.scalar(
        select(KnowledgeNode)
        .join(CourseCatalog, CourseCatalog.id == KnowledgeNode.course_id)
        .where(
            KnowledgeNode.id == body.node_id,
            KnowledgeNode.course_id == body.course_id,
            CourseCatalog.published.is_(True),
        )
    )
    if node is None:
        raise ResourceJobScopeError("governed course node not found")
    source_ids = [str(item) for item in node.source_ids]
    if not source_ids:
        raise ResourceJobScopeError("governed course node has no approved sources")
    context_digest = _canonical_digest(
        {
            "course_id": str(node.course_id),
            "node_id": str(node.id),
            "content_version": node.content_version,
            "source_ids": source_ids,
        }
    )
    job = ResourceJobRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        student_id=student_id,
        course_id=body.course_id,
        node_id=body.node_id,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        status=ResourceJobStatus.QUEUED,
        requested_types=[item.value for item in body.resource_types],
        source_ids=source_ids,
        context_digest=context_digest,
        progress_percent=0,
    )
    db.add(job)
    db.flush()
    return job


def get_student_resource_job(
    db: Session,
    *,
    job_id: UUID,
    tenant_id: UUID,
    student_id: UUID,
) -> ResourceJobRecord:
    job = db.scalar(
        select(ResourceJobRecord).where(
            ResourceJobRecord.id == job_id,
            ResourceJobRecord.tenant_id == tenant_id,
            ResourceJobRecord.student_id == student_id,
        )
    )
    if job is None:
        raise ResourceJobScopeError("resource job not found")
    return job


def resource_job_view(db: Session, job: ResourceJobRecord) -> ResourceJobView:
    artifacts = list(
        db.scalars(
            select(LearningResourceRecord)
            .where(LearningResourceRecord.job_id == job.id)
            .order_by(LearningResourceRecord.created_at, LearningResourceRecord.version)
        )
    )
    object_by_resource = {
        item.resource_id: item
        for item in db.scalars(
            select(ResourceObjectRecord).where(
                ResourceObjectRecord.resource_id.in_([artifact.id for artifact in artifacts])
            )
        )
    }
    artifact_views: list[ResourceArtifactView] = []
    for artifact in artifacts:
        stored = object_by_resource.get(artifact.id)
        object_view = (
            None
            if stored is None
            else ResourceObjectView(
                object_key=stored.object_key,
                digest=stored.digest,
                mime_type=stored.mime_type,
                size_bytes=stored.size_bytes,
                version=stored.version,
                published=stored.published,
            )
        )
        artifact_views.append(
            ResourceArtifactView(
                id=artifact.id,
                resource_type=artifact.resource_type.value,
                version=artifact.version,
                status=artifact.status.value,
                source_ids=artifact.source_ids,
                context_digest=artifact.context_digest,
                content_digest=artifact.content_digest,
                object=object_view,
                published_at=(
                    artifact.published_at.isoformat() if artifact.published_at is not None else None
                ),
            )
        )
    return ResourceJobView(
        id=job.id,
        course_id=job.course_id,
        node_id=job.node_id,
        status=job.status.value,
        progress_percent=job.progress_percent,
        requested_types=job.requested_types,
        artifacts=artifact_views,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )
