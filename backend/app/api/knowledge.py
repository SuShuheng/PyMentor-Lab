"""Knowledge graph edges query API (BE-021).

Returns the course's prerequisite DAG (nodes + edges) with a per-node mastery
join for the requesting student. The graph structure is course-scoped and
shared across tenants; the ``mastery_status`` field is student-scoped.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.knowledge import (
    KnowledgeGraph,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
)
from app.db import get_db
from app.knowledge_assets import (
    KnowledgeGraphNotFoundError,
    load_knowledge_graph,
)
from app.models import CourseCatalog, User
from app.rbac import get_current_user

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge-graph"])


def _resolve_course_id(db: Session, course_id: UUID | None) -> UUID:
    if course_id is not None:
        return course_id
    published = db.scalar(
        select(CourseCatalog.id)
        .where(CourseCatalog.published.is_(True))
        .order_by(CourseCatalog.created_at, CourseCatalog.id)
        .limit(1)
    )
    if published is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no published course available",
        )
    return published


@router.get("/graph", response_model=KnowledgeGraph)
async def get_knowledge_graph(
    course_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KnowledgeGraph:
    resolved_course_id = _resolve_course_id(db, course_id)
    try:
        projection = load_knowledge_graph(db, course_id=resolved_course_id, student_id=user.id)
    except KnowledgeGraphNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return KnowledgeGraph(
        course_id=projection.course_id,
        nodes=[
            KnowledgeGraphNode(
                node_id=node.node_id,
                title=node.title,
                chapter_id=node.chapter_id,
                mastery_status=node.mastery_status,
            )
            for node in projection.nodes
        ],
        edges=[
            KnowledgeGraphEdge(
                from_node_id=edge.from_node_id,
                to_node_id=edge.to_node_id,
                kind="prerequisite",
            )
            for edge in projection.edges
        ],
    )
