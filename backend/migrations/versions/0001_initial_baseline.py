"""Initial baseline.

Establishes the migration chain. No tables yet — BE-003 (persistence and
consistency foundation) introduces the real schema for formal state, evidence,
audit, Outbox, and idempotency. This revision proves upgrade/rollback is
repeatable before any DDL lands.

Revision ID: 0001
Revises:
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Bootstrap migration: intentionally empty (no application tables yet)."""
    # op and sa are imported for parity with later migrations; BE-003 adds DDL.
    _ = op
    _ = sa


def downgrade() -> None:
    """Roll back to the empty (pre-migration) state."""
    pass
