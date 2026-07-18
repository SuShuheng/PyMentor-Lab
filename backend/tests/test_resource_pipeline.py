"""BE-007 five-resource job, object version, and dual-gate domain tests."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.resources import (
    InMemoryObjectStore,
    InMemoryResourceJobRepository,
    ResourceArtifactStatus,
    ResourceGate,
    ResourceGateError,
    ResourceJobConflict,
    ResourceJobRequest,
    ResourceJobStatus,
    ResourcePipeline,
    ResourceType,
)

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
STUDENT_ID = UUID("22222222-2222-4222-8222-222222222222")
COURSE_ID = UUID("69408047-3b99-5fb2-b383-81f7314ecd5d")
NODE_ID = UUID("9512e5ec-f547-51b3-b0df-c5b3a877da9e")
SOURCE_ID = UUID("33333333-3333-4333-8333-333333333333")
ALL_TYPES = tuple(ResourceType)


def _request(*, node_id: UUID = NODE_ID) -> ResourceJobRequest:
    return ResourceJobRequest(
        tenant_id=TENANT_ID,
        student_id=STUDENT_ID,
        course_id=COURSE_ID,
        node_id=node_id,
        resource_types=ALL_TYPES,
        source_ids=(SOURCE_ID,),
        context_digest="a" * 64,
    )


def _pipeline() -> ResourcePipeline:
    return ResourcePipeline(InMemoryResourceJobRepository(), InMemoryObjectStore())


def _record_and_publish(
    pipeline: ResourcePipeline, job_id: UUID, resource_type: ResourceType
) -> None:
    artifact = pipeline.record_artifact(
        job_id=job_id,
        resource_type=resource_type,
        content=f"content:{resource_type.value}".encode(),
        mime_type="application/json",
        source_ids=(SOURCE_ID,),
    )
    pipeline.record_review(
        job_id=job_id,
        artifact_id=artifact.id,
        gate=ResourceGate.FACTUAL,
        passed=True,
        findings=(),
    )
    pipeline.record_review(
        job_id=job_id,
        artifact_id=artifact.id,
        gate=ResourceGate.COMPLIANCE,
        passed=True,
        findings=(),
    )
    pipeline.publish(job_id=job_id, artifact_id=artifact.id)


def test_duplicate_job_key_returns_same_job_and_conflicting_payload_is_rejected() -> None:
    pipeline = _pipeline()

    first = pipeline.start(_request(), idempotency_key="resource-job-1")
    duplicate = pipeline.start(_request(), idempotency_key="resource-job-1")

    assert duplicate is first
    assert first.status is ResourceJobStatus.QUEUED
    assert len(pipeline.repository.jobs) == 1

    with pytest.raises(ResourceJobConflict, match="different resource request"):
        pipeline.start(
            _request(node_id=UUID("44444444-4444-4444-8444-444444444444")),
            idempotency_key="resource-job-1",
        )


def test_first_published_resource_is_partial_and_all_five_make_job_ready() -> None:
    pipeline = _pipeline()
    job = pipeline.start(_request(), idempotency_key="resource-job-2")

    _record_and_publish(pipeline, job.id, ResourceType.STRUCTURE_CARD)

    assert job.status is ResourceJobStatus.PARTIAL_READY
    assert job.progress_percent == 20
    first = job.artifacts[ResourceType.STRUCTURE_CARD]
    assert first.status is ResourceArtifactStatus.PUBLISHED
    assert first.version == 1
    assert first.object_version == 1
    assert first.object_key.startswith(f"resources/{TENANT_ID}/{job.id}/structure-card/v1/")
    assert first.digest == first.object_digest
    assert first.size_bytes == len(b"content:STRUCTURE_CARD")

    for resource_type in ALL_TYPES:
        if resource_type is not ResourceType.STRUCTURE_CARD:
            _record_and_publish(pipeline, job.id, resource_type)

    assert job.status is ResourceJobStatus.READY
    assert job.progress_percent == 100
    assert len(job.artifacts) == 5


def test_missing_sources_and_failed_gate_never_publish() -> None:
    pipeline = _pipeline()
    job = pipeline.start(_request(), idempotency_key="resource-job-3")

    with pytest.raises(ResourceGateError, match="approved source"):
        pipeline.record_artifact(
            job_id=job.id,
            resource_type=ResourceType.MICRO_LECTURE,
            content=b"source-free content",
            mime_type="text/markdown",
            source_ids=(),
        )

    artifact = pipeline.record_artifact(
        job_id=job.id,
        resource_type=ResourceType.MICRO_LECTURE,
        content=b"review me",
        mime_type="text/markdown",
        source_ids=(SOURCE_ID,),
    )
    pipeline.record_review(
        job_id=job.id,
        artifact_id=artifact.id,
        gate=ResourceGate.FACTUAL,
        passed=True,
        findings=(),
    )
    pipeline.record_review(
        job_id=job.id,
        artifact_id=artifact.id,
        gate=ResourceGate.COMPLIANCE,
        passed=False,
        findings=("CONTENT_REJECTED",),
    )

    with pytest.raises(ResourceGateError, match="both review gates"):
        pipeline.publish(job_id=job.id, artifact_id=artifact.id)

    assert artifact.status is ResourceArtifactStatus.REJECTED
    assert job.status is ResourceJobStatus.FAILED_FINAL
    assert pipeline.object_store.is_published(artifact.object_key) is False


def test_object_digest_is_verified_before_review() -> None:
    store = InMemoryObjectStore()
    pipeline = ResourcePipeline(InMemoryResourceJobRepository(), store)
    job = pipeline.start(_request(), idempotency_key="resource-job-4")
    artifact = pipeline.record_artifact(
        job_id=job.id,
        resource_type=ResourceType.NOTEBOOK_TASK,
        content=b"original",
        mime_type="application/x-ipynb+json",
        source_ids=(SOURCE_ID,),
    )
    store.tamper(artifact.object_key, b"changed")

    with pytest.raises(ResourceGateError, match="digest"):
        pipeline.record_review(
            job_id=job.id,
            artifact_id=artifact.id,
            gate=ResourceGate.FACTUAL,
            passed=True,
            findings=(),
        )

    assert artifact.status is ResourceArtifactStatus.REJECTED
    assert job.status is ResourceJobStatus.FAILED_RETRYABLE
