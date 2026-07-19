"""Real-PostgreSQL fixtures for the INT-005 admin operations gate."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

os.environ.setdefault("PYMENTOR_BOOTSTRAP_ON_STARTUP", "false")

TEST_DB_URL = os.environ.get(
    "PYMENTOR_DATABASE_URL",
    "postgresql+psycopg://pymentor:pymentor_dev@127.0.0.1:5432/pymentor",
)
CANONICAL_COURSE_ID = "69408047-3b99-5fb2-b383-81f7314ecd5d"


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Connect to the disposable compose PostgreSQL service or skip explicitly."""

    if not TEST_DB_URL.startswith("postgres"):
        pytest.skip("PostgreSQL is required for the INT-005 gate")
    engine = create_engine(TEST_DB_URL, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on the live service
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine: Engine) -> Iterator[Session]:
    """Exercise real constraints while rolling every scenario back afterward."""

    from uuid import UUID

    from app.knowledge_seed import seed_published_course
    from app.models import CourseCatalog

    with Session(db_engine) as seed_session:
        if seed_session.get(CourseCatalog, UUID(CANONICAL_COURSE_ID)) is None:
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
