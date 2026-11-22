"""Engine and session factory. Rule R3: only the Repository/ORM layer opens connections."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models import Base

_settings = get_settings()
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=10 if not _settings.database_url.startswith("sqlite") else 5,
    connect_args=_connect_args,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


# Columns added after v1.5. create_all() never alters an existing table, so a database
# created by an earlier version gets them here (idempotent, additive only).
_ADDED_COLUMNS = {
    "agents": {"description": "TEXT NOT NULL DEFAULT ''"},
    "workflow_steps": {"instruction_override": "TEXT"},
}


def create_schema() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def drop_schema() -> None:
    Base.metadata.drop_all(engine)


def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
