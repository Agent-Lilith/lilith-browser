from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import TSVECTOR
from pgvector.sqlalchemy import Vector

EMBEDDING_DIM = 768


class Base(DeclarativeBase):
    pass


class HistoryEntry(Base):
    """One row per URL (deduplicated). Ingest aggregates visits into last_visit_time and visit_count."""
    __tablename__ = "history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)
    snippet: Mapped[Optional[str]] = mapped_column(Text)
    domain: Mapped[Optional[str]] = mapped_column(String(253))
    last_visit_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    visit_count: Mapped[int] = mapped_column(Integer, default=0)
    browser: Mapped[Optional[str]] = mapped_column(String)
    embedding: Mapped[Optional[Vector]] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    search_tsv = mapped_column(TSVECTOR, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Bookmark(Base):
    __tablename__ = "bookmarks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)
    snippet: Mapped[Optional[str]] = mapped_column(Text)
    folder: Mapped[Optional[str]] = mapped_column(Text)
    added_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    browser: Mapped[Optional[str]] = mapped_column(String)
    embedding: Mapped[Optional[Vector]] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    search_tsv = mapped_column(TSVECTOR, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
