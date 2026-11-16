"""Engine and session factory. Rule R3: only the Repository/ORM layer opens connections."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
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


def create_schema() -> None:
    Base.metadata.create_all(engine)


def drop_schema() -> None:
    Base.metadata.drop_all(engine)


def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
