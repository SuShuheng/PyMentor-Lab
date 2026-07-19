"""Integration-lane pytest fixtures for the INT-003 learning-loop gate.

The integration workstream owns ``tests/e2e/**`` (CONTRACT "Cross-track
acceptance"). This conftest reproduces the *real PostgreSQL* ``db_session``
seam that BE-002 introduced in ``backend/tests/conftest.py`` so the learning
loop can be exercised against the same formal-state tables the owner tests
use, without modifying the backend owner's conftest.

Design notes:

- The session-scoped engine connects once to the docker-compose PostgreSQL
  service (configurable via ``PYMENTOR_DATABASE_URL``). If PostgreSQL is not
  reachable the gate is *skipped*, never silently passed — exactly the real-DB
  contract the integration lane enforces.
- Each test runs inside a connection transaction with a nested savepoint, and
  the teardown rolls the outer transaction back. This isolates integration
  tests from each other while still exercising real schema constraints,
  partial unique indexes, and transactional outbox atomicity.
- The canonical published course is seeded once per engine session when absent
  so all learning fixtures reference governed course/node UUIDs.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

# Disable startup bootstrap so the test app never triggers an out-of-band
# database connection that would pollute savepoint isolation.
os.environ.setdefault("PYMENTOR_BOOTSTRAP_ON_STARTUP", "false")

TEST_DB_URL = os.environ.get(
    "PYMENTOR_DATABASE_URL",
    "postgresql+psycopg://pymentor:pymentor_dev@localhost:5432/pymentor",
)


def _has_postgres() -> bool:
    return TEST_DB_URL.startswith("postgres")


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Session-scoped real PostgreSQL engine.

    Reused across tests to amortise the first TCP handshake. If PostgreSQL is
    unavailable the whole session is skipped — the integration gate never
    substitutes an in-memory or mock store for formal state.
    """

    if not _has_postgres():
        pytest.skip("PostgreSQL not configured for this test run")
    engine = create_engine(TEST_DB_URL, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on live service
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine: Engine) -> Iterator[Session]:
    """Per-test real-PostgreSQL session running inside a savepoint.

    Business code that commits only advances the nested savepoint; the outer
    transaction is rolled back on teardown so tests stay isolated while still
    exercising real schema constraints and transactional outbox atomicity.
    """

    from app.knowledge_seed import seed_published_course
    from app.models import CourseCatalog

    course_id = type("CourseId", (), {"value": "69408047-3b99-5fb2-b383-81f7314ecd5d"})().value
    from uuid import UUID

    canonical_course = UUID(course_id)
    with Session(db_engine) as seed_session:
        if seed_session.get(CourseCatalog, canonical_course) is None:
            seed_published_course(seed_session)
            seed_session.commit()

    connection = db_engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    nested = connection.begin_nested()
    try:
        yield session
    finally:
        session.close()
        if nested.is_active:
            nested.rollback()
        if outer.is_active:
            outer.rollback()
        connection.close()
