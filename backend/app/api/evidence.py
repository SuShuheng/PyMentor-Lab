"""证据查询路由：学生查看自己的学习证据。

设计：证据可按学生、课程、节点、时间查询。
RBAC：学生只能查自己的证据（require_tenant_match 隐含于 student_id 过滤）。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.contracts.consistency import EvidenceEvent
from app.db import get_db
from app.evidence import list_evidence
from app.models.identity import User
from app.rbac import get_current_user

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])


@router.get("", response_model=list[EvidenceEvent])
async def get_my_evidence(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    course_id: UUID | None = Query(default=None),
    node_id: UUID | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[EvidenceEvent]:
    """查询当前学生的学习证据（只能查自己的）。"""
    events = list_evidence(
        db,
        tenant_id=user.tenant_id,
        student_id=user.id,
        course_id=course_id,
        node_id=node_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    return [
        EvidenceEvent(
            id=str(e.id),
            tenant_id=str(e.tenant_id),
            student_id=str(e.student_id),
            event_id=e.event_id,
            event_type=e.event_type,
            trace_id=e.trace_id,
            payload=e.payload,
            evidence_confidence=e.evidence_confidence,
            created_at=e.created_at.isoformat(),
            course_id=str(e.course_id) if e.course_id else None,
            node_id=str(e.node_id) if e.node_id else None,
            task_id=str(e.task_id) if e.task_id else None,
        )
        for e in events
    ]
