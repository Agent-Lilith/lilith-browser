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
            },
            {
                "source_name": "browser_bookmarks",
                "source_class": "personal",
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
) -> dict:
    top_k = min(max(1, top_k), 100)
    all_results = []
    timing_ms = {}
    methods_executed: list[str] = []

    with db_session() as db:
        embedder = Embedder()
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
