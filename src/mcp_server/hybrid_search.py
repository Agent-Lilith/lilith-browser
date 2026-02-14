"""Hybrid search engines for browser history and bookmarks: structured + fulltext + vector."""

import logging
import time
from datetime import date, datetime
from datetime import time as dtime
from typing import Any

from sqlalchemy import func, literal_column, select

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
            stmt = stmt.where(
                HistoryEntry.last_visit_time >= _parse_date_bound(str(value))
            )
        elif field == "date_before" and value:
            stmt = stmt.where(
                HistoryEntry.last_visit_time
                <= _parse_date_bound(str(value), end_of_day=True)
            )
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
            stmt = stmt.where(
                Bookmark.added_at <= _parse_date_bound(str(value), end_of_day=True)
            )
    return stmt


def _history_to_result(
    entry: HistoryEntry, scores: dict[str, float], methods: list[str]
) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "source": "browser_history",
        "source_class": "personal",
        "title": entry.title or "No title",
        "snippet": entry.snippet or "",
        "timestamp": entry.last_visit_time.isoformat()
        if entry.last_visit_time
        else None,
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


def _bookmark_to_result(
    bm: Bookmark, scores: dict[str, float], methods: list[str]
) -> dict[str, Any]:
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
        "provenance": f"bookmarked in {bm.folder or 'root'}"
        + (f" on {bm.added_at.strftime('%Y-%m-%d')}" if bm.added_at else ""),
    }


from common.search import BaseHybridSearchEngine


class HybridHistorySearchEngine(BaseHybridSearchEngine[HistoryEntry]):
    """Hybrid search over browser history: structured + fulltext + vector."""

    def __init__(self, db: Any, embedder: Any = None) -> None:
        self.db = db
        self.embedder = embedder

    def search(
        self,
        query: str = "",
        methods: list | None = None,
        filters: list | None = None,
        top_k: int = 10,
    ):
        methods = methods or ["structured", "fulltext", "vector"]
        timing: dict[str, float] = {}
        methods_executed: list[str] = []
        all_results: dict[Any, dict[str, Any]] = {}

        def add_batch(batch: list, method_name: str) -> None:
            if not batch:
                return
            methods_executed.append(method_name)
            for item, score in batch:
                item_id = self._get_item_id(item)
                if item_id not in all_results:
                    all_results[item_id] = {"item": item, "scores": {}, "methods": []}
                all_results[item_id]["scores"][method_name] = score
                if method_name not in all_results[item_id]["methods"]:
                    all_results[item_id]["methods"].append(method_name)

        t_start = time.monotonic()
        if "structured" in methods:
            t0 = time.monotonic()
            try:
                add_batch(self._structured(filters, top_k * 2), "structured")
            except Exception as e:
                logger.warning("Structured search failed: %s", e)
            timing["structured"] = round((time.monotonic() - t0) * 1000, 1)
        if "fulltext" in methods and query and query.strip():
            t0 = time.monotonic()
            try:
                add_batch(self._fulltext(query, filters, top_k * 2), "fulltext")
            except Exception as e:
                logger.warning("Fulltext search failed: %s", e)
            timing["fulltext"] = round((time.monotonic() - t0) * 1000, 1)
        if "vector" in methods and query and query.strip():
            t0 = time.monotonic()
            try:
                add_batch(self._vector(query, filters, top_k * 2), "vector")
            except Exception as e:
                logger.warning("Vector search failed: %s", e)
            timing["vector"] = round((time.monotonic() - t0) * 1000, 1)

        fusion_results = []
        for res in all_results.values():
            final_score = max(res["scores"].values())
            fusion_results.append(
                (
                    self._format_result(res["item"], res["scores"], res["methods"]),
                    final_score,
                )
            )
        fusion_results.sort(key=lambda x: x[1], reverse=True)
        results = [x[0] for x in fusion_results[:top_k]]
        timing["total"] = round((time.monotonic() - t_start) * 1000, 1)
        return results, timing, methods_executed

    def _get_item_id(self, item: HistoryEntry) -> int:
        return item.id

    def _structured(
        self, filters: list[dict] | None, limit: int
    ) -> list[tuple[HistoryEntry, float]]:
        stmt = select(HistoryEntry)
        stmt = _apply_history_filters(stmt, filters)
        stmt = stmt.order_by(HistoryEntry.last_visit_time.desc().nullslast()).limit(
            limit
        )
        rows = self.db.execute(stmt).scalars().all()
        return [(row, max(0.3, 1.0 - i * 0.03)) for i, row in enumerate(rows)]

    def _fulltext(
        self, query: str, filters: list[dict] | None, limit: int
    ) -> list[tuple[HistoryEntry, float]]:
        tsquery = func.plainto_tsquery("simple", query)
        rank = func.ts_rank_cd(HistoryEntry.search_tsv, tsquery)
        stmt = select(HistoryEntry, rank.label("rank"))
        stmt = _apply_history_filters(stmt, filters)
        stmt = stmt.where(HistoryEntry.search_tsv.isnot(None))
        stmt = stmt.where(literal_column("search_tsv").op("@@")(tsquery))
        stmt = stmt.order_by(
            rank.desc(), HistoryEntry.last_visit_time.desc().nullslast()
        ).limit(limit)
        rows = self.db.execute(stmt).all()
        return [(row[0], min(1.0, max(0.1, float(row[1])))) for row in rows]

    def _vector(
        self, query: str, filters: list[dict] | None, limit: int
    ) -> list[tuple[HistoryEntry, float]]:
        embedding = self.embedder.encode_sync(query)
        if not embedding or not any(x != 0 for x in embedding):
            return []
        dist = HistoryEntry.embedding.cosine_distance(embedding)
        stmt = select(HistoryEntry, dist.label("distance"))
        stmt = _apply_history_filters(stmt, filters)
        stmt = stmt.where(HistoryEntry.embedding.isnot(None))
        stmt = stmt.order_by(
            dist, HistoryEntry.last_visit_time.desc().nullslast()
        ).limit(limit)
        rows = self.db.execute(stmt).all()
        return [(row[0], max(0.0, min(1.0, 1.0 - float(row[1])))) for row in rows]

    def _get_item_by_id(self, item_id: int, **kwargs) -> HistoryEntry | None:
        return self.db.get(HistoryEntry, item_id)

    def _format_result(
        self, item: HistoryEntry, scores: dict[str, float], methods: list[str]
    ) -> dict[str, Any]:
        return _history_to_result(item, scores, methods)

    def count(self, filters: list[dict] | None = None) -> dict:
        """Return total count of matching history entries."""
        stmt = select(func.count()).select_from(HistoryEntry)
        stmt = _apply_history_filters(stmt, filters)
        total = self.db.execute(stmt).scalar() or 0
        return {
            "count": total,
            "results": [],
            "total_available": total,
            "mode": "count",
            "methods_executed": ["count"],
            "timing_ms": {},
            "error": None,
        }

    def aggregate(
        self,
        group_by: str,
        filters: list[dict] | None = None,
        top_n: int = 10,
    ) -> dict:
        """Return top groups by count. group_by: domain."""
        if group_by != "domain":
            return {"results": [], "aggregates": [], "mode": "aggregate", "error": None}
        stmt = (
            select(HistoryEntry.domain, func.count().label("cnt"))
            .where(HistoryEntry.domain.isnot(None))
            .where(HistoryEntry.domain != "")
        )
        stmt = _apply_history_filters(stmt, filters)
        stmt = (
            stmt.group_by(HistoryEntry.domain)
            .order_by(func.count().desc())
            .limit(top_n)
        )
        rows = self.db.execute(stmt).all()
        aggregates = [
            {
                "group_value": str(row[0] or ""),
                "count": row[1],
                "label": str(row[0] or ""),
                "metadata": {},
            }
            for row in rows
        ]
        return {
            "results": [],
            "total_available": 0,
            "mode": "aggregate",
            "aggregates": aggregates,
            "methods_executed": ["aggregate"],
            "timing_ms": {},
            "error": None,
        }


class HybridBookmarkSearchEngine(BaseHybridSearchEngine[Bookmark]):
    """Hybrid search over bookmarks: structured + fulltext + vector."""

    def __init__(self, db: Any, embedder: Any = None) -> None:
        self.db = db
        self.embedder = embedder

    def search(
        self,
        query: str = "",
        methods: list | None = None,
        filters: list | None = None,
        top_k: int = 10,
    ):
        methods = methods or ["structured", "fulltext", "vector"]
        timing: dict[str, float] = {}
        methods_executed: list[str] = []
        all_results: dict[Any, dict[str, Any]] = {}

        def add_batch(batch: list, method_name: str) -> None:
            if not batch:
                return
            methods_executed.append(method_name)
            for item, score in batch:
                item_id = self._get_item_id(item)
                if item_id not in all_results:
                    all_results[item_id] = {"item": item, "scores": {}, "methods": []}
                all_results[item_id]["scores"][method_name] = score
                if method_name not in all_results[item_id]["methods"]:
                    all_results[item_id]["methods"].append(method_name)

        t_start = time.monotonic()
        if "structured" in methods:
            t0 = time.monotonic()
            try:
                add_batch(self._structured(filters, top_k * 2), "structured")
            except Exception as e:
                logger.warning("Structured search failed: %s", e)
            timing["structured"] = round((time.monotonic() - t0) * 1000, 1)
        if "fulltext" in methods and query and query.strip():
            t0 = time.monotonic()
            try:
                add_batch(self._fulltext(query, filters, top_k * 2), "fulltext")
            except Exception as e:
                logger.warning("Fulltext search failed: %s", e)
            timing["fulltext"] = round((time.monotonic() - t0) * 1000, 1)
        if "vector" in methods and query and query.strip():
            t0 = time.monotonic()
            try:
                add_batch(self._vector(query, filters, top_k * 2), "vector")
            except Exception as e:
                logger.warning("Vector search failed: %s", e)
            timing["vector"] = round((time.monotonic() - t0) * 1000, 1)

        fusion_results = []
        for res in all_results.values():
            final_score = max(res["scores"].values())
            fusion_results.append(
                (
                    self._format_result(res["item"], res["scores"], res["methods"]),
                    final_score,
                )
            )
        fusion_results.sort(key=lambda x: x[1], reverse=True)
        results = [x[0] for x in fusion_results[:top_k]]
        timing["total"] = round((time.monotonic() - t_start) * 1000, 1)
        return results, timing, methods_executed

    def _get_item_id(self, item: Bookmark) -> int:
        return item.id

    def _structured(
        self, filters: list[dict] | None, limit: int
    ) -> list[tuple[Bookmark, float]]:
        stmt = select(Bookmark)
        stmt = _apply_bookmark_filters(stmt, filters)
        stmt = stmt.order_by(Bookmark.added_at.desc().nullslast()).limit(limit)
        rows = self.db.execute(stmt).scalars().all()
        return [(row, max(0.3, 1.0 - i * 0.03)) for i, row in enumerate(rows)]

    def _fulltext(
        self, query: str, filters: list[dict] | None, limit: int
    ) -> list[tuple[Bookmark, float]]:
        tsquery = func.plainto_tsquery("simple", query)
        rank = func.ts_rank_cd(Bookmark.search_tsv, tsquery)
        stmt = select(Bookmark, rank.label("rank"))
        stmt = _apply_bookmark_filters(stmt, filters)
        stmt = stmt.where(Bookmark.search_tsv.isnot(None))
        stmt = stmt.where(literal_column("search_tsv").op("@@")(tsquery))
        stmt = stmt.order_by(rank.desc(), Bookmark.added_at.desc().nullslast()).limit(
            limit
        )
        rows = self.db.execute(stmt).all()
        return [(row[0], min(1.0, max(0.1, float(row[1])))) for row in rows]

    def _vector(
        self, query: str, filters: list[dict] | None, limit: int
    ) -> list[tuple[Bookmark, float]]:
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

    def _get_item_by_id(self, item_id: int, **kwargs) -> Bookmark | None:
        return self.db.get(Bookmark, item_id)

    def _format_result(
        self, item: Bookmark, scores: dict[str, float], methods: list[str]
    ) -> dict[str, Any]:
        return _bookmark_to_result(item, scores, methods)

    def count(self, filters: list[dict] | None = None) -> dict:
        """Return total count of matching bookmarks."""
        stmt = select(func.count()).select_from(Bookmark)
        stmt = _apply_bookmark_filters(stmt, filters)
        total = self.db.execute(stmt).scalar() or 0
        return {
            "count": total,
            "results": [],
            "total_available": total,
            "mode": "count",
            "methods_executed": ["count"],
            "timing_ms": {},
            "error": None,
        }

    def aggregate(
        self,
        group_by: str,
        filters: list[dict] | None = None,
        top_n: int = 10,
    ) -> dict:
        """Return top groups by count. group_by: folder."""
        if group_by != "folder":
            return {"results": [], "aggregates": [], "mode": "aggregate", "error": None}
        stmt = (
            select(Bookmark.folder, func.count().label("cnt"))
            .where(Bookmark.folder.isnot(None))
            .where(Bookmark.folder != "")
        )
        stmt = _apply_bookmark_filters(stmt, filters)
        stmt = stmt.group_by(Bookmark.folder).order_by(func.count().desc()).limit(top_n)
        rows = self.db.execute(stmt).all()
        aggregates = [
            {
                "group_value": str(row[0] or ""),
                "count": row[1],
                "label": str(row[0] or ""),
                "metadata": {},
            }
            for row in rows
        ]
        return {
            "results": [],
            "total_available": 0,
            "mode": "aggregate",
            "aggregates": aggregates,
            "methods_executed": ["aggregate"],
            "timing_ms": {},
            "error": None,
        }
