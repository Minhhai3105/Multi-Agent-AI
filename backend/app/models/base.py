from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

# BIGSERIAL on PostgreSQL (Architecture Design 6.2.6), INTEGER on SQLite for local tests.
BigId = BigInteger().with_variant(Integer(), "sqlite")
# JSONB on PostgreSQL for semi-structured AI data, plain JSON elsewhere.
JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass
