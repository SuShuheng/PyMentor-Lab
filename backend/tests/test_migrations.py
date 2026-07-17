"""Migration round-trip test: upgrade then downgrade must be repeatable.

Uses a throwaway file-based SQLite database so no external PostgreSQL is
required at the bootstrap stage. BE-003 adds real schema and a PostgreSQL CI
path; this test only proves the migration chain is reversible (PRD test matrix:
"数据库迁移测试").
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "migrations" / "alembic.ini"


def _make_config(db_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent))
    os.environ["PYMENTOR_DATABASE_URL"] = db_url
    return cfg


def test_migration_upgrade_downgrade_round_trip() -> None:
    """`upgrade head` then `downgrade base` must succeed on a clean database."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        db_url = f"sqlite:///{db_path.as_posix()}"
        cfg = _make_config(db_url)

        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        # Re-upgrade proves idempotency after a rollback.
        command.upgrade(cfg, "head")
