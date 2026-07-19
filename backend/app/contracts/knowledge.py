"""Knowledge graph wire contracts (BE-021).

Exposes the course's prerequisite DAG (nodes + edges) plus a per-node mastery
join for the requesting student. The graph is read-only and course-scoped; the
mastery status on each node is the student's current state (or null if the
node has never been touched).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.learning import MasteryStatusContract


class KnowledgeGraphNode(BaseModel):
    """One knowledge node annotated with the requesting student's mastery state."""

    model_config = ConfigDict(extra="forbid")

    node_id: UUID
    title: str = Field(min_length=1, max_length=255)
    chapter_id: UUID
    mastery_status: MasteryStatusContract | None = None


class KnowledgeGraphEdge(BaseModel):
    """A directed prerequisite relation: ``from_node_id`` must precede ``to_node_id``."""

    model_config = ConfigDict(extra="forbid")

    from_node_id: UUID
    to_node_id: UUID
    kind: Literal["prerequisite"]


class KnowledgeGraph(BaseModel):
    """Nodes + edges of one course's knowledge graph, scoped to the caller."""

    model_config = ConfigDict(extra="forbid")

    course_id: UUID
    nodes: list[KnowledgeGraphNode] = Field(min_length=1)
    edges: list[KnowledgeGraphEdge]
