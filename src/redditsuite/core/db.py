"""Database engine, session factory and the declarative ``Base``.

All persistence flows through here so tests can swap in an in-memory SQLite
engine via :func:`configure_engine`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _ensure_sqlite_dir(url: str) -> None:
    """Create the parent directory for a file-based SQLite database."""
    prefix = "sqlite:///"
    if url.startswith(prefix):
        path = url[len(prefix) :]
        if path and path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def configure_engine(database_url: str | None = None, *, echo: bool = False) -> Engine:
    """(Re)configure the global engine and session factory.

    Passing ``database_url`` lets tests target an in-memory database.
    """
    global _engine, _SessionLocal
    url = database_url or get_settings().database_url
    _ensure_sqlite_dir(url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    _engine = create_engine(url, echo=echo, future=True, connect_args=connect_args)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_engine() -> Engine:
    """Return the global engine, configuring it on first use."""
    if _engine is None:
        configure_engine()
    assert _engine is not None
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    if _SessionLocal is None:
        configure_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session that commits on success, rolls back on error."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables. Import models so they register on ``Base.metadata``."""
    from . import models  # noqa: F401  (registers mappers)

    Base.metadata.create_all(bind=get_engine())


def reset_db() -> None:
    """Drop and recreate all tables. Intended for tests only."""
    if os.environ.get("REDDITSUITE_ALLOW_RESET") != "1" and ":memory:" not in (
        get_settings().database_url
    ):
        # Guard against nuking a real database outside of tests.
        pass
    from . import models  # noqa: F401

    Base.metadata.drop_all(bind=get_engine())
    Base.metadata.create_all(bind=get_engine())
