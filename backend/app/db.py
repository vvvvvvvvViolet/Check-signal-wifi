"""SQLAlchemy engine / session wiring."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATABASE_URL

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)

if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver level
        cur = dbapi_conn.cursor()
        # WAL keeps the monitor writer from blocking dashboard readers.
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    from . import models  # noqa: F401  (registers the mappers)

    Base.metadata.create_all(engine)
    if DATABASE_URL.startswith("sqlite"):
        _apply_column_additions()


# Columns added after the first release. `create_all` creates missing *tables*
# but never alters an existing one, so a database written by an earlier version
# would keep working right up until the first query touching a new column.
#
# This is deliberately the smallest thing that works. A real migration tool is
# warranted as soon as the schema starts changing shape rather than just growing.
_ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("survey_points", "neighbors", "JSON"),
]


def _apply_column_additions() -> None:

    with engine.begin() as conn:
        for table, column, ddl_type in _ADDED_COLUMNS:
            existing = {
                row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            }
            if not existing:
                continue  # table itself is new; create_all just made it correctly
            if column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
