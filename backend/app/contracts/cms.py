"""BE-027 minimal course CMS wire contracts.

These contracts are the editable surface the admin CMS exposes on top of the
governed knowledge catalogue. They are intentionally a subset of the full
asset shape (``app.knowledge_assets``) — only the fields an editor may change
in-place appear here. Structural identity (``node_id``/``question_id``) and
cross-references such as ``chapter_id`` / ``mastery_policy_id`` are read-only
from the CMS and come back in the view for context.

Validation is NOT redefined here: every PUT rebuilds a synthetic full
``CourseAssetBundle`` document and runs the existing
``knowledge_assets.validate_course_document`` so the cycle check, source
whitelist, reference integrity, and schema rules stay the single source of
truth.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge_assets import SemanticVersion


class _StrictCmsModel(BaseModel):
    """CMS contracts reject undeclared fields to keep the wire surface narrow."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Knowledge node
# --------------------------------------------------------------------------- #
class CmsNodeUpdate(_StrictCmsModel):
    """Editable fields of a knowledge node.

    Every field is optional: omitted fields retain the published value, which
    lets the editor patch one objective without re-submitting the whole node.
    ``content_version`` cannot be set directly — the PUT advances it.
    """

    title: str | None = Field(default=None, min_length=1)
    learning_objectives: list[str] | None = Field(default=None, min_length=1)
    prerequisites: list[UUID] | None = Field(default=None)
    misconceptions: list[str] | None = Field(default=None, min_length=1)
    examples: list[str] | None = Field(default=None, min_length=1)
    diagnostic_items: list[UUID] | None = Field(default=None, min_length=1)
    practice_templates: list[UUID] | None = Field(default=None, min_length=1)
    source_ids: list[UUID] | None = Field(default=None, min_length=1)


class CmsNodeView(_StrictCmsModel):
    """Read shape returned by GET / PUT / publish endpoints."""

    node_id: UUID
    course_id: UUID
    chapter_id: UUID
    title: str
    learning_objectives: list[str]
    prerequisites: list[UUID]
    misconceptions: list[str]
    examples: list[str]
    diagnostic_items: list[UUID]
    practice_templates: list[UUID]
    mastery_policy_id: UUID
    source_ids: list[UUID]
    content_version: SemanticVersion


# --------------------------------------------------------------------------- #
# Question template
# --------------------------------------------------------------------------- #
class CmsQuestionUpdate(_StrictCmsModel):
    """Editable fields of a question template.

    ``prompt_template`` is the primary editing surface. ``answer_schema`` and
    ``parameter_schema`` may be patched but must keep the asset contract's
    shape (any dict; semantic validity is the validator's job).
    """

    prompt_template: str | None = Field(default=None, min_length=1)
    parameter_schema: dict[str, object] | None = None
    answer_schema: dict[str, object] | None = None
    test_case_ids: list[UUID] | None = Field(default=None, min_length=1)
    source_ids: list[UUID] | None = Field(default=None, min_length=1)


class CmsQuestionView(_StrictCmsModel):
    question_id: UUID
    node_id: UUID
    kind: str
    prompt_template: str
    parameter_schema: dict[str, object]
    answer_schema: dict[str, object]
    test_case_ids: list[UUID]
    source_ids: list[UUID]
    content_version: SemanticVersion


# --------------------------------------------------------------------------- #
# Publish
# --------------------------------------------------------------------------- #
class CmsPublishRequest(_StrictCmsModel):
    """Body for the explicit publish step.

    ``notes`` is the editor's release note; it is recorded (length-capped) in
    the audit ``detail`` so reviewers can correlate a published version with
    its justification. No field here can mutate the asset itself.
    """

    notes: str | None = Field(default=None, max_length=512)


class CmsPublishView(_StrictCmsModel):
    """Confirmation shape returned by POST publish."""

    node_id: UUID | None = None
    question_id: UUID | None = None
    published: bool
    content_version: SemanticVersion
    actor_user_id: UUID
