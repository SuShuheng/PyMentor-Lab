"""BE-007 PostgreSQL-backed resource publication coordinator tests."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.resources import ResourceJobCreate
from app.models import (
    LearningResourceRecord,
    ResourceJobRecord,
    ResourceObjectRecord,
    ResourceReviewRecord,
    Tenant,
    User,
    UserStatus,
)
from app.resource_jobs import create_resource_job, resource_request_digest
from app.resource_publication import SqlResourcePublicationService
from app.resources import (
    InMemoryObjectStore,
    ResourceArtifactStatus,
    ResourceGate,
    ResourceGateError,
    ResourceJobStatus,
    ResourceType,
)

COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")
NODE_ID = UUID("9512e5ec-f547-51b3-b0df-c5b3a877da9e")


def _job(db: Session) -> ResourceJobRecord:
    tenant = Tenant(slug=f"resource-publish-{uuid4().hex}", name="Resource Publish")
    db.add(tenant)
    db.flush()
    student = User(
        tenant_id=tenant.id,
        email=f"resource-publish-{uuid4().hex}@example.com",
        password_hash="not-used",
        status=UserStatus.ACTIVE,
    )
    db.add(student)
    db.flush()
    body = ResourceJobCreate(
        course_id=COURSE_ID,
        node_id=NODE_ID,
        resource_types=[item.value for item in ResourceType],
    )
    return create_resource_job(
        db,
        body,
        tenant_id=tenant.id,
        student_id=student.id,
        idempotency_key=f"publish-{uuid4().hex}",
        request_digest=resource_request_digest(body, tenant_id=tenant.id, student_id=student.id),
    )


def _pass_and_publish(
    service: SqlResourcePublicationService,
    resource: LearningResourceRecord,
) -> None:
    service.review(
        resource_id=resource.id,
        gate=ResourceGate.FACTUAL,
        passed=True,
        findings=(),
        reviewer="deterministic-validator-v1",
    )
    service.review(
        resource_id=resource.id,
        gate=ResourceGate.COMPLIANCE,
        passed=True,
        findings=(),
        reviewer="moderation-provider-v1",
    )
    service.publish(resource_id=resource.id)


def test_persists_progressive_publication_until_all_five_ready(db_session: Session) -> None:
    store = InMemoryObjectStore()
    service = SqlResourcePublicationService(db_session, store)
    job = _job(db_session)
    source_ids = tuple(UUID(item) for item in job.source_ids)

    first = service.stage(
        job_id=job.id,
        resource_type=ResourceType.STRUCTURE_CARD,
        content=b'{"title":"Loop card"}',
        mime_type="application/json",
        source_ids=source_ids,
    )
    _pass_and_publish(service, first)

    assert first.status is ResourceArtifactStatus.PUBLISHED
    assert job.status is ResourceJobStatus.PARTIAL_READY
    assert job.progress_percent == 20
    first_object = db_session.scalar(
        select(ResourceObjectRecord).where(ResourceObjectRecord.resource_id == first.id)
    )
    assert first_object is not None
    assert first_object.published is True
    assert store.is_published(first_object.object_key) is True

    for resource_type in ResourceType:
        if resource_type is ResourceType.STRUCTURE_CARD:
            continue
        resource = service.stage(
            job_id=job.id,
            resource_type=resource_type,
            content=f"content:{resource_type.value}".encode(),
            mime_type="application/octet-stream",
            source_ids=source_ids,
        )
        _pass_and_publish(service, resource)

    assert job.status is ResourceJobStatus.READY
    assert job.progress_percent == 100
    assert db_session.scalar(select(func.count()).select_from(LearningResourceRecord)) == 5
    assert db_session.scalar(select(func.count()).select_from(ResourceObjectRecord)) == 5
    assert db_session.scalar(select(func.count()).select_from(ResourceReviewRecord)) == 10


def test_failed_compliance_review_is_durable_and_cannot_publish(db_session: Session) -> None:
    store = InMemoryObjectStore()
    service = SqlResourcePublicationService(db_session, store)
    job = _job(db_session)
    resource = service.stage(
        job_id=job.id,
        resource_type=ResourceType.MICRO_LECTURE,
        content=b"review me",
        mime_type="text/markdown",
        source_ids=tuple(UUID(item) for item in job.source_ids),
    )
    service.review(
        resource_id=resource.id,
        gate=ResourceGate.FACTUAL,
        passed=True,
        findings=(),
        reviewer="deterministic-validator-v1",
    )
    service.review(
        resource_id=resource.id,
        gate=ResourceGate.COMPLIANCE,
        passed=False,
        findings=("CONTENT_REJECTED",),
        reviewer="moderation-provider-v1",
    )

    with pytest.raises(ResourceGateError, match="both review gates"):
        service.publish(resource_id=resource.id)

    assert resource.status is ResourceArtifactStatus.REJECTED
    assert job.status is ResourceJobStatus.FAILED_FINAL
    review = db_session.scalar(
        select(ResourceReviewRecord).where(
            ResourceReviewRecord.resource_id == resource.id,
            ResourceReviewRecord.gate == ResourceGate.COMPLIANCE,
        )
    )
    assert review is not None
    assert review.passed is False
    assert review.findings == ["CONTENT_REJECTED"]

    with pytest.raises(ResourceGateError, match="terminal"):
        service.stage(
            job_id=job.id,
            resource_type=ResourceType.STRUCTURE_CARD,
            content=b"must not stage after a final rejection",
            mime_type="application/json",
            source_ids=tuple(UUID(item) for item in job.source_ids),
        )


def test_digest_mismatch_fails_retryably_before_review_is_written(db_session: Session) -> None:
    store = InMemoryObjectStore()
    service = SqlResourcePublicationService(db_session, store)
    job = _job(db_session)
    resource = service.stage(
        job_id=job.id,
        resource_type=ResourceType.NOTEBOOK_TASK,
        content=b"original",
        mime_type="application/x-ipynb+json",
        source_ids=tuple(UUID(item) for item in job.source_ids),
    )
    stored = db_session.scalar(
        select(ResourceObjectRecord).where(ResourceObjectRecord.resource_id == resource.id)
    )
    assert stored is not None
    store.tamper(stored.object_key, b"tampered")

    with pytest.raises(ResourceGateError, match="digest"):
        service.review(
            resource_id=resource.id,
            gate=ResourceGate.FACTUAL,
            passed=True,
            findings=(),
            reviewer="deterministic-validator-v1",
        )

    assert resource.status is ResourceArtifactStatus.REJECTED
    assert job.status is ResourceJobStatus.FAILED_RETRYABLE
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ResourceReviewRecord)
            .where(ResourceReviewRecord.resource_id == resource.id)
        )
        == 0
    )
