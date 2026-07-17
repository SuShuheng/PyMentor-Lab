"""Database foundation: engine, session factory, declarative Base, FastAPI dep.

Established in BE-002 (identity). BE-003 (persistence and consistency) layers
the Outbox/idempotency/evidence repositories on top of this same engine and
Base. PostgreSQL is the formal-state authority (CONTRACT.md "Service and data
contracts").
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models and Alembic autogenerate."""


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a transactional session per request.

    The session is closed (not committed) on exit; callers commit explicitly so
    formal-state writes pair with their Outbox/event rows atomically (BE-003).
    """

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
