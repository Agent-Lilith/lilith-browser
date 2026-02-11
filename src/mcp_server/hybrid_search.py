"""Hybrid search engines for browser history and bookmarks: structured + fulltext + vector."""

import logging
import time
from datetime import date, datetime, time as dtime
from typing import Any

from sqlalchemy import func, select, literal_column
from sqlalchemy.orm import Session

from core.embeddings import Embedder
from core.models import Bookmark, HistoryEntry

logger = logging.getLogger(__name__)


def _parse_date_bound(s: str, end_of_day: bool = False) -> datetime:
    s = s.strip()
    if not s:
        raise ValueError("Empty date string")
    if "T" in s or " " in s:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    d = date.fromisoformat(s)
    if end_of_day:
        return datetime.combine(d, dtime(23, 59, 59, 999999))
    return datetime.combine(d, dtime(0, 0, 0))


def _cap_limit(limit: int) -> int:
    return min(max(1, limit), 100)


def _apply_history_filters(stmt, filters: list[dict[str, Any]] | None):
    """Apply filter clauses to a history query."""
    stmt = stmt.where(HistoryEntry.deleted_at.is_(None))
    if not filters:
        return stmt
    for f in filters:
        field = f.get("field", "")
        value = f.get("value")
        if field == "date_after" and value:
            stmt = stmt.where(HistoryEntry.last_visit_time >= _parse_date_bound(str(value)))
        elif field == "date_before" and value:
            stmt = stmt.where(HistoryEntry.last_visit_time <= _parse_date_bound(str(value), end_of_day=True))
        elif field == "domain" and value:
            stmt = stmt.where(HistoryEntry.domain.ilike(f"%{value}%"))
    return stmt


def _apply_bookmark_filters(stmt, filters: list[dict[str, Any]] | None):
    """Apply filter clauses to a bookmarks query."""
    stmt = stmt.where(Bookmark.deleted_at.is_(None))
    if not filters:
        return stmt
    for f in filters:
        field = f.get("field", "")
        value = f.get("value")
        if field == "folder" and value:
            stmt = stmt.where(Bookmark.folder.ilike(f"%{value}%"))
        elif field == "date_after" and value:
            stmt = stmt.where(Bookmark.added_at >= _parse_date_bound(str(value)))
        elif field == "date_before" and value:
            stmt = stmt.where(Bookmark.added_at <= _parse_date_bound(str(value), end_of_day=True))
    return stmt


def _history_to_result(entry: HistoryEntry, scores: dict[str, float], methods: list[str]) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "source": "browser_history",
        "source_class": "personal",
        "title": entry.title or "No title",
        "snippet": entry.snippet or "",
        "timestamp": entry.last_visit_time.isoformat() if entry.last_visit_time else None,
        "scores": scores,
        "methods_used": methods,
        "metadata": {
            "url": entry.url or "",
            "domain": entry.domain or "",
            "visit_count": entry.visit_count or 0,
            "type": "history",
        },
        "provenance": f"visited {entry.domain or entry.url or '?'} on {entry.last_visit_time.strftime('%Y-%m-%d') if entry.last_visit_time else '?'}",
    }


def _bookmark_to_result(bm: Bookmark, scores: dict[str, float], methods: list[str]) -> dict[str, Any]:
    return {
        "id": str(bm.id),
        "source": "browser_bookmarks",
        "source_class": "personal",
        "title": bm.title or "No title",
        "snippet": bm.snippet or "",
        "timestamp": bm.added_at.isoformat() if bm.added_at else None,
        "scores": scores,
        "methods_used": methods,
        "metadata": {
            "url": bm.url or "",
            "folder": bm.folder or "",
            "type": "bookmark",
        },
        "provenance": f"bookmarked in {bm.folder or 'root'}" + (f" on {bm.added_at.strftime('%Y-%m-%d')}" if bm.added_at else ""),
    }


class HybridHistorySearchEngine:
    """Hybrid search over browser history: structured + fulltext + vector."""

    def __init__(self, db: Session, embedder: Embedder) -> None:
        self.db = db
        self.embedder = embedder

    def search(
        self,
        query: str = "",
        methods: list[str] | None = None,
        filters: list[dict[str, Any]] | None = None,
        top_k: int = 10,
    ) -> tuple[list[dict[str, Any]], dict[str, float], list[str]]:
        """Returns (results, timing_ms, methods_executed)."""
        top_k = _cap_limit(top_k)
        if methods is None:
            methods = self._auto_select(query, filters)

        all_results: dict[int, dict] = {}  # id -> result data
        timing_ms: dict[str, float] = {}
        methods_executed: list[str] = []

        if "structured" in methods and filters:
            t0 = time.monotonic()
            for entry, score in self._structured(filters, top_k):
                eid = entry.id
                if eid not in all_results:
                    all_results[eid] = {"entry": entry, "scores": {}, "methods": []}
                all_results[eid]["scores"]["structured"] = score
                all_results[eid]["methods"].append("structured")
            timing_ms["structured"] = round((time.monotonic() - t0) * 1000, 1)
            methods_executed.append("structured")

        if "fulltext" in methods and query.strip():
            t0 = time.monotonic()
            for entry, score in self._fulltext(query, filters, top_k):
                eid = entry.id
                if eid not in all_results:
                    all_results[eid] = {"entry": entry, "scores": {}, "methods": []}
                all_results[eid]["scores"]["fulltext"] = score
                if "fulltext" not in all_results[eid]["methods"]:
                    all_results[eid]["methods"].append("fulltext")
            timing_ms["fulltext"] = round((time.monotonic() - t0) * 1000, 1)
            methods_executed.append("fulltext")

        if "vector" in methods and query.strip():
            t0 = time.monotonic()
            for entry, score in self._vector(query, filters, top_k):
                eid = entry.id
                if eid not in all_results:
                    all_results[eid] = {"entry": entry, "scores": {}, "methods": []}
                all_results[eid]["scores"]["vector"] = score
                if "vector" not in all_results[eid]["methods"]:
                    all_results[eid]["methods"].append("vector")
            timing_ms["vector"] = round((time.monotonic() - t0) * 1000, 1)
            methods_executed.append("vector")

        # Fuse scores
        weights = {"structured": 1.0, "fulltext": 0.85, "vector": 0.7}
        scored: list[tuple[float, dict]] = []
        for data in all_results.values():
            total_w = sum(weights.get(m, 0.5) for m in data["scores"])
            total_s = sum(data["scores"][m] * weights.get(m, 0.5) for m in data["scores"])
            final = total_s / total_w if total_w > 0 else 0.0
            result = _history_to_result(data["entry"], data["scores"], data["methods"])
            scored.append((final, result))

        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored[:top_k]], timing_ms, methods_executed

    def _auto_select(self, query: str, filters: list[dict] | None) -> list[str]:
        methods = []
        if filters:
            methods.append("structured")
        if query and query.strip():
            methods.append("fulltext")
            methods.append("vector")
        if not methods:
            methods = ["structured"]
        return methods

    def _structured(self, filters: list[dict] | None, limit: int) -> list[tuple[HistoryEntry, float]]:
        stmt = select(HistoryEntry)
        stmt = _apply_history_filters(stmt, filters)
        stmt = stmt.order_by(HistoryEntry.last_visit_time.desc().nullslast()).limit(limit)
        rows = self.db.execute(stmt).scalars().all()
        return [(row, max(0.3, 1.0 - i * 0.03)) for i, row in enumerate(rows)]

    def _fulltext(self, query: str, filters: list[dict] | None, limit: int) -> list[tuple[HistoryEntry, float]]:
        tsquery = func.plainto_tsquery("simple", query)
        rank = func.ts_rank_cd(HistoryEntry.search_tsv, tsquery)
        stmt = select(HistoryEntry, rank.label("rank"))
        stmt = _apply_history_filters(stmt, filters)
        stmt = stmt.where(HistoryEntry.search_tsv.isnot(None))
        stmt = stmt.where(literal_column("search_tsv").op("@@")(tsquery))
        stmt = stmt.order_by(rank.desc(), HistoryEntry.last_visit_time.desc().nullslast()).limit(limit)
        rows = self.db.execute(stmt).all()
        return [(row[0], min(1.0, max(0.1, float(row[1])))) for row in rows]

    def _vector(self, query: str, filters: list[dict] | None, limit: int) -> list[tuple[HistoryEntry, float]]:
        embedding = self.embedder.encode_sync(query)
        if not embedding or not any(x != 0 for x in embedding):
            return []
        dist = HistoryEntry.embedding.cosine_distance(embedding)
        stmt = select(HistoryEntry, dist.label("distance"))
        stmt = _apply_history_filters(stmt, filters)
        stmt = stmt.where(HistoryEntry.embedding.isnot(None))
        stmt = stmt.order_by(dist, HistoryEntry.last_visit_time.desc().nullslast()).limit(limit)
        rows = self.db.execute(stmt).all()
        return [(row[0], max(0.0, min(1.0, 1.0 - float(row[1])))) for row in rows]


class HybridBookmarkSearchEngine:
    """Hybrid search over bookmarks: structured + fulltext + vector."""

    def __init__(self, db: Session, embedder: Embedder) -> None:
        self.db = db
        self.embedder = embedder

    def search(
        self,
        query: str = "",
        methods: list[str] | None = None,
        filters: list[dict[str, Any]] | None = None,
        top_k: int = 10,
    ) -> tuple[list[dict[str, Any]], dict[str, float], list[str]]:
        top_k = _cap_limit(top_k)
        if methods is None:
            methods = self._auto_select(query, filters)

        all_results: dict[int, dict] = {}
        timing_ms: dict[str, float] = {}
        methods_executed: list[str] = []

        if "structured" in methods and filters:
            t0 = time.monotonic()
            for bm, score in self._structured(filters, top_k):
                bid = bm.id
                if bid not in all_results:
                    all_results[bid] = {"entry": bm, "scores": {}, "methods": []}
                all_results[bid]["scores"]["structured"] = score
                all_results[bid]["methods"].append("structured")
            timing_ms["structured"] = round((time.monotonic() - t0) * 1000, 1)
            methods_executed.append("structured")

        if "fulltext" in methods and query.strip():
            t0 = time.monotonic()
            for bm, score in self._fulltext(query, filters, top_k):
                bid = bm.id
                if bid not in all_results:
                    all_results[bid] = {"entry": bm, "scores": {}, "methods": []}
                all_results[bid]["scores"]["fulltext"] = score
                if "fulltext" not in all_results[bid]["methods"]:
                    all_results[bid]["methods"].append("fulltext")
            timing_ms["fulltext"] = round((time.monotonic() - t0) * 1000, 1)
            methods_executed.append("fulltext")

        if "vector" in methods and query.strip():
            t0 = time.monotonic()
            for bm, score in self._vector(query, filters, top_k):
                bid = bm.id
                if bid not in all_results:
                    all_results[bid] = {"entry": bm, "scores": {}, "methods": []}
                all_results[bid]["scores"]["vector"] = score
                if "vector" not in all_results[bid]["methods"]:
                    all_results[bid]["methods"].append("vector")
            timing_ms["vector"] = round((time.monotonic() - t0) * 1000, 1)
            methods_executed.append("vector")

        weights = {"structured": 1.0, "fulltext": 0.85, "vector": 0.7}
        scored: list[tuple[float, dict]] = []
        for data in all_results.values():
            total_w = sum(weights.get(m, 0.5) for m in data["scores"])
            total_s = sum(data["scores"][m] * weights.get(m, 0.5) for m in data["scores"])
            final = total_s / total_w if total_w > 0 else 0.0
            result = _bookmark_to_result(data["entry"], data["scores"], data["methods"])
            scored.append((final, result))

        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored[:top_k]], timing_ms, methods_executed

    def _auto_select(self, query: str, filters: list[dict] | None) -> list[str]:
        methods = []
        if filters:
            methods.append("structured")
        if query and query.strip():
            methods.append("fulltext")
            methods.append("vector")
        if not methods:
            methods = ["structured"]
        return methods

    def _structured(self, filters: list[dict] | None, limit: int) -> list[tuple[Bookmark, float]]:
        stmt = select(Bookmark)
        stmt = _apply_bookmark_filters(stmt, filters)
        stmt = stmt.order_by(Bookmark.added_at.desc().nullslast()).limit(limit)
        rows = self.db.execute(stmt).scalars().all()
        return [(row, max(0.3, 1.0 - i * 0.03)) for i, row in enumerate(rows)]

    def _fulltext(self, query: str, filters: list[dict] | None, limit: int) -> list[tuple[Bookmark, float]]:
        tsquery = func.plainto_tsquery("simple", query)
        rank = func.ts_rank_cd(Bookmark.search_tsv, tsquery)
        stmt = select(Bookmark, rank.label("rank"))
        stmt = _apply_bookmark_filters(stmt, filters)
        stmt = stmt.where(Bookmark.search_tsv.isnot(None))
        stmt = stmt.where(literal_column("search_tsv").op("@@")(tsquery))
        stmt = stmt.order_by(rank.desc(), Bookmark.added_at.desc().nullslast()).limit(limit)
        rows = self.db.execute(stmt).all()
        return [(row[0], min(1.0, max(0.1, float(row[1])))) for row in rows]

    def _vector(self, query: str, filters: list[dict] | None, limit: int) -> list[tuple[Bookmark, float]]:
        embedding = self.embedder.encode_sync(query)
        if not embedding or not any(x != 0 for x in embedding):
            return []
        dist = Bookmark.embedding.cosine_distance(embedding)
        stmt = select(Bookmark, dist.label("distance"))
        stmt = _apply_bookmark_filters(stmt, filters)
        stmt = stmt.where(Bookmark.embedding.isnot(None))
        stmt = stmt.order_by(dist, Bookmark.added_at.desc().nullslast()).limit(limit)
        rows = self.db.execute(stmt).all()
        return [(row[0], max(0.0, min(1.0, 1.0 - float(row[1])))) for row in rows]
