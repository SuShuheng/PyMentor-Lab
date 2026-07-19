"""Cross-process resource generation and authoritative publication coordinator."""

from __future__ import annotations

import base64
import hashlib
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.config import Settings
from app.db import SessionLocal
from app.models import KnowledgeNode, KnowledgeSource, ResourceJobRecord
from app.object_store import MinioObjectStore, MinioObjectStoreSettings
from app.resource_publication import SqlResourcePublicationService
from app.resources import ResourceGate, ResourceJobStatus, ResourceType

_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_ALLOWED_MIME_TYPES = {
    "application/json",
    "application/x-ipynb+json",
    "image/svg+xml",
    "text/markdown",
}


class _WorkerArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_base64: str = Field(min_length=1, max_length=3 * _MAX_ARTIFACT_BYTES)
    content_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    context_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    fallback_used: bool
    mime_type: str = Field(min_length=1, max_length=128)
    resource_type: ResourceType
    source_ids: list[UUID] = Field(min_length=1, max_length=32)


class _WorkerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifacts: list[_WorkerArtifact] = Field(min_length=1, max_length=5)
    job_id: UUID
    status: str


def _worker_payload(
    job: ResourceJobRecord, node: KnowledgeNode, sources: list[KnowledgeSource]
) -> dict[str, Any]:
    source_lines = "\n".join(
        f"[source:{source.id}] {source.title} ({source.url}) · {source.content_scope}"
        for source in sources
    )
    learning_need = "; ".join(node.learning_objectives) or node.title
    return {
        "job_id": str(job.id),
        "learning_need": learning_need,
        "resource_types": job.requested_types,
        "context": {
            "question": f"Create bounded learning resources for {node.title}",
            "prompt": (
                "Use only the governed course-node facts and citations below.\n"
                f"Node: {node.title}\nObjectives: {learning_need}\n"
                f"Examples: {'; '.join(node.examples)}\n{source_lines}"
            ),
            "citations": [
                {
                    "sourceId": str(source.id),
                    "title": source.title,
                    "url": source.url,
                    "excerptDigest": job.context_digest,
                }
                for source in sources
            ],
            "contextDigest": job.context_digest,
        },
    }


def _mark_failed(job_id: UUID, error_code: str) -> None:
    with SessionLocal() as db:
        job = db.get(ResourceJobRecord, job_id)
        if job is not None and job.status not in {
            ResourceJobStatus.READY,
            ResourceJobStatus.FAILED_FINAL,
            ResourceJobStatus.CANCELLED,
        }:
            job.status = ResourceJobStatus.FAILED_RETRYABLE
            job.error_code = error_code[:64]
            db.commit()


def process_resource_job(job_id: UUID, settings: Settings) -> None:
    """Generate in the Node Worker, then review/publish via PostgreSQL + MinIO."""

    try:
        if len(settings.worker_internal_secret) < 32:
            raise RuntimeError("worker internal secret is not configured")
        with SessionLocal() as db:
            job = db.get(ResourceJobRecord, job_id)
            if job is None or job.status is not ResourceJobStatus.QUEUED:
                return
            node = db.get(KnowledgeNode, job.node_id)
            if node is None:
                raise RuntimeError("governed node is missing")
            source_uuids = [UUID(value) for value in job.source_ids]
            sources = list(
                db.scalars(select(KnowledgeSource).where(KnowledgeSource.id.in_(source_uuids)))
            )
            if {source.id for source in sources} != set(source_uuids):
                raise RuntimeError("governed source metadata is incomplete")
            job.status = ResourceJobStatus.GENERATING
            db.commit()
            payload = _worker_payload(job, node, sources)

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                settings.worker_resource_url,
                headers={"Authorization": f"Bearer {settings.worker_internal_secret}"},
                json=payload,
            )
            response.raise_for_status()
        result = _WorkerResponse.model_validate(response.json())
        if result.job_id != job_id or result.status != "READY":
            raise RuntimeError("worker response identity or status mismatch")
        if len({item.resource_type for item in result.artifacts}) != len(result.artifacts):
            raise RuntimeError("worker returned duplicate resource types")

        object_store = MinioObjectStore(
            MinioObjectStoreSettings.from_application_settings(settings)
        )
        for artifact in result.artifacts:
            content = base64.b64decode(artifact.content_base64, validate=True)
            if not content or len(content) > _MAX_ARTIFACT_BYTES:
                raise RuntimeError("worker artifact size is outside the accepted boundary")
            if hashlib.sha256(content).hexdigest() != artifact.content_digest:
                raise RuntimeError("worker artifact digest mismatch")
            with SessionLocal() as db:
                job = db.get(ResourceJobRecord, job_id)
                if job is None:
                    raise RuntimeError("resource job disappeared")
                if artifact.resource_type.value not in job.requested_types:
                    raise RuntimeError("worker returned an unrequested resource type")
                if artifact.context_digest != job.context_digest:
                    raise RuntimeError("worker context digest mismatch")
                if {str(value) for value in artifact.source_ids} != set(job.source_ids):
                    raise RuntimeError("worker source binding mismatch")

                publication = SqlResourcePublicationService(db, object_store)
                resource = publication.stage(
                    job_id=job_id,
                    resource_type=artifact.resource_type,
                    content=content,
                    mime_type=artifact.mime_type,
                    source_ids=tuple(artifact.source_ids),
                )
                factual_passed = all(
                    f"[source:{source_id}]" in content.decode("utf-8", errors="ignore")
                    or artifact.resource_type is not ResourceType.MICRO_LECTURE
                    for source_id in artifact.source_ids
                )
                publication.review(
                    resource_id=resource.id,
                    gate=ResourceGate.FACTUAL,
                    passed=factual_passed,
                    findings=() if factual_passed else ("missing governed citation",),
                    reviewer="worker-source-binding-v1",
                )
                compliance_passed = artifact.mime_type in _ALLOWED_MIME_TYPES
                publication.review(
                    resource_id=resource.id,
                    gate=ResourceGate.COMPLIANCE,
                    passed=compliance_passed,
                    findings=() if compliance_passed else ("unsupported media type",),
                    reviewer="api-compliance-policy-v1",
                )
                if factual_passed and compliance_passed:
                    publication.publish(resource_id=resource.id)
                db.commit()
    except Exception:
        _mark_failed(job_id, "RESOURCE_PROCESSING_FAILED")
