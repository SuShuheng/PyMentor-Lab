"""Five-resource generation aggregate with versioned objects and dual gates.

The aggregate is deliberately storage-agnostic. BE-007 persistence adapters use
the same transitions; the in-memory ports below provide deterministic unit
coverage without weakening the publication rules.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4


class ResourceType(StrEnum):
    MICRO_LECTURE = "MICRO_LECTURE"
    STRUCTURE_CARD = "STRUCTURE_CARD"
    TRACE_ANIMATION = "TRACE_ANIMATION"
    LAYERED_EXERCISE = "LAYERED_EXERCISE"
    NOTEBOOK_TASK = "NOTEBOOK_TASK"


class ResourceJobStatus(StrEnum):
    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    GENERATING = "GENERATING"
    PARTIAL_READY = "PARTIAL_READY"
    REVIEWING = "REVIEWING"
    READY = "READY"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    CANCELLED = "CANCELLED"


class ResourceArtifactStatus(StrEnum):
    STAGED = "STAGED"
    REVIEWING = "REVIEWING"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"


class ResourceGate(StrEnum):
    FACTUAL = "FACTUAL"
    COMPLIANCE = "COMPLIANCE"


class ResourceJobConflict(ValueError):
    """An idempotency key was reused for a different logical request."""


class ResourceGateError(ValueError):
    """A resource cannot cross a deterministic publication boundary."""


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return _digest(encoded)


@dataclass(frozen=True, slots=True)
class ResourceJobRequest:
    tenant_id: UUID
    student_id: UUID
    course_id: UUID
    node_id: UUID
    resource_types: tuple[ResourceType, ...]
    source_ids: tuple[UUID, ...]
    context_digest: str

    def __post_init__(self) -> None:
        if not self.resource_types or len(set(self.resource_types)) != len(self.resource_types):
            raise ValueError("resource types must be non-empty and unique")
        if not self.source_ids or len(set(self.source_ids)) != len(self.source_ids):
            raise ResourceGateError("resource job requires at least one approved source")
        if len(self.context_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.context_digest
        ):
            raise ValueError("context digest must be lowercase SHA-256")

    @property
    def digest(self) -> str:
        return _canonical_digest(
            {
                "tenant_id": str(self.tenant_id),
                "student_id": str(self.student_id),
                "course_id": str(self.course_id),
                "node_id": str(self.node_id),
                "resource_types": [item.value for item in self.resource_types],
                "source_ids": [str(item) for item in self.source_ids],
                "context_digest": self.context_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class ResourceReview:
    gate: ResourceGate
    passed: bool
    findings: tuple[str, ...]


@dataclass(slots=True)
class ResourceArtifact:
    id: UUID
    resource_type: ResourceType
    version: int
    source_ids: tuple[UUID, ...]
    context_digest: str
    object_key: str
    object_version: int
    object_digest: str
    digest: str
    mime_type: str
    size_bytes: int
    status: ResourceArtifactStatus = ResourceArtifactStatus.STAGED
    reviews: dict[ResourceGate, ResourceReview] = field(default_factory=dict)


@dataclass(slots=True)
class ResourceJob:
    id: UUID
    idempotency_key: str
    request_digest: str
    request: ResourceJobRequest
    status: ResourceJobStatus = ResourceJobStatus.QUEUED
    artifacts: dict[ResourceType, ResourceArtifact] = field(default_factory=dict)

    @property
    def progress_percent(self) -> int:
        published = sum(
            artifact.status is ResourceArtifactStatus.PUBLISHED
            for artifact in self.artifacts.values()
        )
        return published * 100 // len(self.request.resource_types)


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    version: int
    digest: str
    mime_type: str
    size_bytes: int


@dataclass(slots=True)
class _ObjectState:
    content: bytes
    metadata: StoredObject
    published: bool = False


class InMemoryObjectStore:
    """Object-store test port that preserves versions, digests, and visibility."""

    def __init__(self) -> None:
        self._objects: dict[str, _ObjectState] = {}

    def put(self, *, key: str, content: bytes, mime_type: str, version: int) -> StoredObject:
        if key in self._objects:
            raise ResourceGateError("object key already exists")
        metadata = StoredObject(
            key=key,
            version=version,
            digest=_digest(content),
            mime_type=mime_type,
            size_bytes=len(content),
        )
        self._objects[key] = _ObjectState(content=bytes(content), metadata=metadata)
        return metadata

    def verify(self, key: str, expected_digest: str) -> bool:
        state = self._objects.get(key)
        return state is not None and _digest(state.content) == expected_digest

    def publish(self, key: str, expected_digest: str) -> None:
        if not self.verify(key, expected_digest):
            raise ResourceGateError("object digest verification failed")
        self._objects[key].published = True

    def is_published(self, key: str) -> bool:
        state = self._objects.get(key)
        return state is not None and state.published

    def tamper(self, key: str, content: bytes) -> None:
        self._objects[key].content = bytes(content)


class InMemoryResourceJobRepository:
    """Idempotent aggregate repository used by the domain and adapter tests."""

    def __init__(self) -> None:
        self.jobs: dict[UUID, ResourceJob] = {}
        self._idempotency: dict[tuple[UUID, str], UUID] = {}

    def start(self, request: ResourceJobRequest, idempotency_key: str) -> ResourceJob:
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("idempotency key must contain between 1 and 128 characters")
        identity = (request.tenant_id, idempotency_key)
        existing_id = self._idempotency.get(identity)
        if existing_id is not None:
            existing = self.jobs[existing_id]
            if existing.request_digest != request.digest:
                raise ResourceJobConflict("idempotency key belongs to a different resource request")
            return existing
        job = ResourceJob(
            id=uuid4(),
            idempotency_key=idempotency_key,
            request_digest=request.digest,
            request=request,
        )
        self.jobs[job.id] = job
        self._idempotency[identity] = job.id
        return job

    def get(self, job_id: UUID) -> ResourceJob:
        try:
            return self.jobs[job_id]
        except KeyError as error:
            raise LookupError("resource job not found") from error


class ResourcePipeline:
    """Authoritative five-resource transition service."""

    def __init__(
        self,
        repository: InMemoryResourceJobRepository,
        object_store: InMemoryObjectStore,
    ) -> None:
        self.repository = repository
        self.object_store = object_store

    def start(self, request: ResourceJobRequest, *, idempotency_key: str) -> ResourceJob:
        return self.repository.start(request, idempotency_key)

    def record_artifact(
        self,
        *,
        job_id: UUID,
        resource_type: ResourceType,
        content: bytes,
        mime_type: str,
        source_ids: tuple[UUID, ...],
    ) -> ResourceArtifact:
        job = self.repository.get(job_id)
        if resource_type not in job.request.resource_types:
            raise ResourceGateError("resource type was not requested by this job")
        if not source_ids or not set(source_ids).issubset(job.request.source_ids):
            raise ResourceGateError("resource artifact requires an approved source")
        if not content:
            raise ResourceGateError("resource artifact content must not be empty")
        if not mime_type or len(mime_type) > 128:
            raise ResourceGateError("resource artifact MIME type is invalid")
        previous = job.artifacts.get(resource_type)
        if previous is not None and previous.status is not ResourceArtifactStatus.REJECTED:
            raise ResourceGateError("resource type already has an active artifact")
        version = 1 if previous is None else previous.version + 1
        artifact_id = uuid4()
        content_digest = _digest(content)
        slug = resource_type.value.lower().replace("_", "-")
        object_key = (
            f"resources/{job.request.tenant_id}/{job.id}/{slug}/v{version}/{content_digest}"
        )
        stored = self.object_store.put(
            key=object_key,
            content=content,
            mime_type=mime_type,
            version=version,
        )
        artifact = ResourceArtifact(
            id=artifact_id,
            resource_type=resource_type,
            version=version,
            source_ids=source_ids,
            context_digest=job.request.context_digest,
            object_key=stored.key,
            object_version=stored.version,
            object_digest=stored.digest,
            digest=content_digest,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
        )
        job.artifacts[resource_type] = artifact
        job.status = ResourceJobStatus.REVIEWING
        return artifact

    def _artifact(self, job: ResourceJob, artifact_id: UUID) -> ResourceArtifact:
        artifact = next(
            (candidate for candidate in job.artifacts.values() if candidate.id == artifact_id),
            None,
        )
        if artifact is None:
            raise LookupError("resource artifact not found")
        return artifact

    def record_review(
        self,
        *,
        job_id: UUID,
        artifact_id: UUID,
        gate: ResourceGate,
        passed: bool,
        findings: tuple[str, ...],
    ) -> ResourceArtifact:
        job = self.repository.get(job_id)
        artifact = self._artifact(job, artifact_id)
        if artifact.status in {ResourceArtifactStatus.PUBLISHED, ResourceArtifactStatus.REJECTED}:
            raise ResourceGateError("resource artifact is already terminal")
        if not self.object_store.verify(artifact.object_key, artifact.object_digest):
            artifact.status = ResourceArtifactStatus.REJECTED
            job.status = ResourceJobStatus.FAILED_RETRYABLE
            raise ResourceGateError("resource object digest verification failed")
        artifact.reviews[gate] = ResourceReview(gate=gate, passed=passed, findings=findings)
        artifact.status = ResourceArtifactStatus.REVIEWING
        job.status = ResourceJobStatus.REVIEWING
        if not passed:
            artifact.status = ResourceArtifactStatus.REJECTED
            job.status = (
                ResourceJobStatus.FAILED_FINAL
                if gate is ResourceGate.COMPLIANCE
                else ResourceJobStatus.FAILED_RETRYABLE
            )
        return artifact

    def publish(self, *, job_id: UUID, artifact_id: UUID) -> ResourceArtifact:
        job = self.repository.get(job_id)
        artifact = self._artifact(job, artifact_id)
        gates_passed = all(
            artifact.reviews.get(gate) is not None and artifact.reviews[gate].passed
            for gate in ResourceGate
        )
        if not gates_passed:
            if any(review.passed is False for review in artifact.reviews.values()):
                artifact.status = ResourceArtifactStatus.REJECTED
            raise ResourceGateError("resource must pass both review gates before publication")
        self.object_store.publish(artifact.object_key, artifact.object_digest)
        artifact.status = ResourceArtifactStatus.PUBLISHED
        published_types = {
            item.resource_type
            for item in job.artifacts.values()
            if item.status is ResourceArtifactStatus.PUBLISHED
        }
        job.status = (
            ResourceJobStatus.READY
            if published_types == set(job.request.resource_types)
            else ResourceJobStatus.PARTIAL_READY
        )
        return artifact
