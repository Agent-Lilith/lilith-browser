"""Upsert Vivaldi data into Postgres and optional embedding backfill."""
import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.embeddings import Embedder
from core.models import EMBEDDING_DIM, Bookmark, HistoryEntry

BROWSER = "vivaldi"
logger = logging.getLogger(__name__)


def _text_for_embedding(title: str | None, url: str, extra: str = "") -> str:
    parts = [title or "", url, extra]
    return " ".join(p for p in parts if p).strip() or url


def _url_digest(url: str) -> bytes:
    return hashlib.sha256(url.encode()).digest()


def upsert_history(db: Session, rows: list[dict]) -> int:
    """Upsert history rows. Returns count of rows processed."""
    for r in rows:
        digest_val = _url_digest(r["url"])
        existing = db.execute(
            select(HistoryEntry).where(
                func.digest(HistoryEntry.url, "sha256") == digest_val,
                HistoryEntry.browser == BROWSER,
            )
        ).scalar_one_or_none()
        if existing:
            existing.title = r.get("title")
            existing.domain = r.get("domain") or None
            existing.last_visit_time = r.get("last_visit_time")
            existing.visit_count = r.get("visit_count", 0)
            existing.updated_at = datetime.now(timezone.utc)
        else:
            db.add(
                HistoryEntry(
                    url=r["url"],
                    title=r.get("title"),
                    snippet=None,
                    domain=r.get("domain") or None,
                    last_visit_time=r.get("last_visit_time"),
                    visit_count=r.get("visit_count", 0),
                    browser=BROWSER,
                )
            )
    db.flush()
    return len(rows)


def upsert_bookmarks(db: Session, rows: list[dict]) -> int:
    """Upsert bookmark rows. Returns count of rows processed."""
    for r in rows:
        folder = r.get("folder") or None
        digest_val = _url_digest(r["url"])
        stmt = select(Bookmark).where(
            func.digest(Bookmark.url, "sha256") == digest_val,
            Bookmark.browser == BROWSER,
        )
        if folder is None:
            stmt = stmt.where(Bookmark.folder.is_(None))
        else:
            stmt = stmt.where(Bookmark.folder == folder)
        existing = db.execute(stmt).scalar_one_or_none()
        if existing:
            existing.title = r.get("title")
            existing.added_at = r.get("added_at")
            existing.updated_at = datetime.now(timezone.utc)
        else:
            db.add(
                Bookmark(
                    url=r["url"],
                    title=r.get("title"),
                    snippet=None,
                    folder=folder,
                    added_at=r.get("added_at"),
                    browser=BROWSER,
                )
            )
    db.flush()
    return len(rows)


def embed_history_batch(db: Session, embedder: Embedder, batch_size: int = 50) -> int:
    """Compute embeddings for history rows where embedding is NULL. Returns count updated."""
    rows = db.execute(
        select(HistoryEntry).where(
            HistoryEntry.browser == BROWSER,
            HistoryEntry.embedding.is_(None),
            HistoryEntry.deleted_at.is_(None),
        ).limit(batch_size)
    ).scalars().all()
    entries = list(rows)
    if not entries:
        return 0
    texts = [_text_for_embedding(e.title, e.url) for e in entries]
    try:
        vectors = embedder.encode_sync(texts)
    except Exception as e:
        logger.warning("Embedding batch failed: %s", e)
        return 0
    if not isinstance(vectors, list) or len(vectors) != len(entries):
        return 0
    now = datetime.now(timezone.utc)
    for e, vec in zip(entries, vectors):
        if isinstance(vec, list) and len(vec) == EMBEDDING_DIM:
            e.embedding = vec
            e.embedding_computed_at = now
    db.flush()
    return len(entries)


def run_embedding_backfill(db: Session, embedder: Embedder, batch_size: int = 50) -> tuple[int, int]:
    """Run embedding backfill for history and bookmarks. Returns (history_count, bookmark_count)."""
    h_total, b_total = 0, 0
    while True:
        n = embed_history_batch(db, embedder, batch_size)
        h_total += n
        if n == 0:
            break
    while True:
        n = embed_bookmarks_batch(db, embedder, batch_size)
        b_total += n
        if n == 0:
            break
    return h_total, b_total


def embed_bookmarks_batch(db: Session, embedder: Embedder, batch_size: int = 50) -> int:
    """Compute embeddings for bookmark rows where embedding is NULL. Returns count updated."""
    rows = db.execute(
        select(Bookmark).where(
            Bookmark.browser == BROWSER,
            Bookmark.embedding.is_(None),
            Bookmark.deleted_at.is_(None),
        ).limit(batch_size)
    ).scalars().all()
    entries = list(rows)
    if not entries:
        return 0
    texts = [_text_for_embedding(e.title, e.url, e.folder or "") for e in entries]
    try:
        vectors = embedder.encode_sync(texts)
    except Exception as e:
        logger.warning("Embedding batch failed: %s", e)
        return 0
    if not isinstance(vectors, list) or len(vectors) != len(entries):
        return 0
    now = datetime.now(timezone.utc)
    for e, vec in zip(entries, vectors):
        if isinstance(vec, list) and len(vec) == EMBEDDING_DIM:
            e.embedding = vec
            e.embedding_computed_at = now
    db.flush()
    return len(entries)
