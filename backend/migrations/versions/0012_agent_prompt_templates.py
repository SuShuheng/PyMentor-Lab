"""Add versioned Agent prompt templates for per-node prompt tuning (BE-020).

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-19

V1.0 hardcoded the system prompts inside the Worker (``AgentDefinition`` carried
public policy metadata only; raw prompts were never stored). BE-020 lets a System
Admin version and publish prompt edits per LangGraph node with audit. The Worker
reads the single published version per node at runtime.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.types import Uuid

revision: str = "0012"
down_revision: str = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_prompt_templates",
        sa.Column("id", Uuid, primary_key=True),
        sa.Column(
            "tenant_id",
            Uuid,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # LangGraph node name: orchestrator | profile | path | resource | coach | assessment.
        sa.Column("node", sa.String(32), nullable=False),
        # Monotonic per (tenant, node): 1, 2, 3, ... in creation order.
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        # Exactly one published version may be true per (tenant, node); the API
        # atomically unpublishes the others on publish.
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_by",
            Uuid,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("version >= 1", name="ck_agent_prompt_templates_version_positive"),
        sa.CheckConstraint(
            "length(system_prompt) >= 1",
            name="ck_agent_prompt_templates_prompt_nonempty",
        ),
        sa.UniqueConstraint(
            "tenant_id", "node", "version", name="uq_agent_prompt_templates_tenant_node_version"
        ),
    )
    for column in ("tenant_id", "node", "version", "published", "created_by", "created_at"):
        op.create_index(f"ix_agent_prompt_templates_{column}", "agent_prompt_templates", [column])
    # At most one published version per (tenant, node).
    op.create_index(
        "uq_agent_prompt_templates_single_published_per_node",
        "agent_prompt_templates",
        ["tenant_id", "node"],
        unique=True,
        postgresql_where=sa.text("published = true"),
    )


def downgrade() -> None:
    op.drop_table("agent_prompt_templates")
