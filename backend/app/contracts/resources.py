"""BE-007 resource-job wire contracts (Pydantic mirror)."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256Digest = str


class StrictResourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceTypeContract(StrEnum):
    MICRO_LECTURE = "MICRO_LECTURE"
    STRUCTURE_CARD = "STRUCTURE_CARD"
    TRACE_ANIMATION = "TRACE_ANIMATION"
    LAYERED_EXERCISE = "LAYERED_EXERCISE"
    NOTEBOOK_TASK = "NOTEBOOK_TASK"


class ResourceJobStatusContract(StrEnum):
    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    GENERATING = "GENERATING"
    PARTIAL_READY = "PARTIAL_READY"
    REVIEWING = "REVIEWING"
    READY = "READY"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    CANCELLED = "CANCELLED"


class ResourceArtifactStatusContract(StrEnum):
    STAGED = "STAGED"
    REVIEWING = "REVIEWING"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"


class ResourceJobCreate(StrictResourceModel):
    course_id: UUID
    node_id: UUID
    resource_types: list[ResourceTypeContract] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique_resource_types(self) -> ResourceJobCreate:
        if len(set(self.resource_types)) != len(self.resource_types):
            raise ValueError("resource types must be unique")
        return self


class ResourceObjectView(StrictResourceModel):
    object_key: str = Field(min_length=1)
    digest: Sha256Digest = Field(pattern=r"^[a-f0-9]{64}$")
    mime_type: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    version: int = Field(ge=1)
    published: bool


class ResourceArtifactView(StrictResourceModel):
    id: UUID
    resource_type: ResourceTypeContract
    version: int = Field(ge=1)
    status: ResourceArtifactStatusContract
    source_ids: list[UUID] = Field(min_length=1)
    context_digest: Sha256Digest = Field(pattern=r"^[a-f0-9]{64}$")
    content_digest: Sha256Digest = Field(pattern=r"^[a-f0-9]{64}$")
    object: ResourceObjectView | None
    published_at: str | None


class ResourceJobView(StrictResourceModel):
    id: UUID
    course_id: UUID
    node_id: UUID
    status: ResourceJobStatusContract
    progress_percent: int = Field(ge=0, le=100)
    requested_types: list[ResourceTypeContract] = Field(min_length=1, max_length=5)
    artifacts: list[ResourceArtifactView]
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
