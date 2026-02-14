import logging

from core.database import db_session
from core.embeddings import Embedder
from mcp_server.hybrid_search import (
    HybridBookmarkSearchEngine,
    HybridHistorySearchEngine,
)

logger = logging.getLogger(__name__)


def get_search_capabilities_tool() -> dict:
    return {
        "schema_version": "1.0",
        "sources": [
            {
                "source_name": "browser_history",
                "source_class": "personal",
                "display_label": "Browser history",
                "supported_methods": ["structured", "fulltext", "vector"],
                "supported_filters": [
                    {
                        "name": "date_after",
                        "type": "date",
                        "operators": ["gte"],
                        "description": "Visited on or after this date",
                    },
                    {
                        "name": "date_before",
                        "type": "date",
                        "operators": ["lte"],
                        "description": "Visited on or before this date",
                    },
                    {
                        "name": "domain",
                        "type": "string",
                        "operators": ["contains"],
                        "description": "Domain substring filter",
                    },
                ],
                "max_limit": 100,
                "default_limit": 10,
                "sort_fields": ["last_visit_time", "relevance"],
                "default_ranking": "vector",
                "supported_modes": ["search", "count", "aggregate"],
                "supported_group_by_fields": ["domain"],
            },
            {
                "source_name": "browser_bookmarks",
                "source_class": "personal",
                "display_label": "Browser bookmarks",
                "supported_methods": ["structured", "fulltext", "vector"],
                "supported_filters": [
                    {
                        "name": "folder",
                        "type": "string",
                        "operators": ["contains"],
                        "description": "Bookmark folder filter",
                    },
                    {
                        "name": "date_after",
                        "type": "date",
                        "operators": ["gte"],
                        "description": "Bookmarked on or after this date",
                    },
                    {
                        "name": "date_before",
                        "type": "date",
                        "operators": ["lte"],
                        "description": "Bookmarked on or before this date",
                    },
                ],
                "max_limit": 100,
                "default_limit": 10,
                "sort_fields": ["added_at", "relevance"],
                "default_ranking": "vector",
                "supported_modes": ["search", "count", "aggregate"],
                "supported_group_by_fields": ["folder"],
            },
        ],
    }


def search_browser_unified_tool(
    query: str = "",
    methods: list[str] | None = None,
    filters: list[dict] | None = None,
    top_k: int = 10,
    search_history: bool = True,
    search_bookmarks: bool = True,
    mode: str = "search",
    group_by: str | None = None,
    aggregate_top_n: int = 10,
) -> dict:
    top_k = min(max(1, top_k), 100)
    aggregate_top_n = min(max(1, aggregate_top_n), 100)

    with db_session() as db:
        embedder = Embedder()
        if mode == "count":
            total = 0
            if search_history:
                total += HybridHistorySearchEngine(db, embedder).count(
                    filters=filters
                )["count"]
            if search_bookmarks:
                total += HybridBookmarkSearchEngine(db, embedder).count(
                    filters=filters
                )["count"]
            return {
                "results": [],
                "total_available": total,
                "count": total,
                "mode": "count",
                "methods_executed": ["count"],
                "timing_ms": {},
                "error": None,
            }
        if mode == "aggregate" and group_by:
            if group_by == "domain" and search_history and not search_bookmarks:
                return HybridHistorySearchEngine(db, embedder).aggregate(
                    group_by="domain",
                    filters=filters,
                    top_n=aggregate_top_n,
                )
            if group_by == "folder" and search_bookmarks and not search_history:
                return HybridBookmarkSearchEngine(db, embedder).aggregate(
                    group_by="folder",
                    filters=filters,
                    top_n=aggregate_top_n,
                )
        all_results = []
        timing_ms = {}
        methods_executed: list[str] = []

        if search_history:
            engine = HybridHistorySearchEngine(db, embedder)
            res, t, m = engine.search(
                query=query, methods=methods, filters=filters, top_k=top_k
            )
            all_results.extend(res)
            timing_ms.update({f"history_{k}": v for k, v in t.items()})
            methods_executed = list(set(methods_executed + m))

        if search_bookmarks:
            engine = HybridBookmarkSearchEngine(db, embedder)
            res, t, m = engine.search(
                query=query, methods=methods, filters=filters, top_k=top_k
            )
            all_results.extend(res)
            timing_ms.update({f"bookmarks_{k}": v for k, v in t.items()})
            methods_executed = list(set(methods_executed + m))

    # Browser-specific fusion for mixed sources
    weights = {"structured": 1.0, "fulltext": 0.85, "vector": 0.7}

    def _fused_score(r: dict) -> float:
        scores = r.get("scores", {})
        if not scores:
            return 0.0
        tw = sum(weights.get(meth, 0.5) for meth in scores)
        ts = sum(scores[meth] * weights.get(meth, 0.5) for meth in scores)
        return ts / tw if tw > 0 else 0.0

    all_results.sort(key=_fused_score, reverse=True)

    return {
        "results": all_results[:top_k],
        "total_available": len(all_results),
        "methods_executed": methods_executed,
        "timing_ms": timing_ms,
        "error": None,
    }
