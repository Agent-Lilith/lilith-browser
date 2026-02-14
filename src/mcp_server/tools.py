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
    search_history: bool = False,
    search_bookmarks: bool = False,
    mode: str = "search",
    group_by: str | None = None,
    aggregate_top_n: int = 10,
) -> dict:
    if search_history == search_bookmarks:
        raise ValueError(
            "Exactly one browser source must be selected (search_history xor search_bookmarks)."
        )

    top_k = min(max(1, top_k), 100)
    aggregate_top_n = min(max(1, aggregate_top_n), 100)

    with db_session() as db:
        embedder = Embedder()
        source = "history" if search_history else "bookmarks"
        if mode == "count":
            if source == "history":
                return HybridHistorySearchEngine(db, embedder).count(filters=filters)
            return HybridBookmarkSearchEngine(db, embedder).count(filters=filters)

        if mode == "aggregate" and group_by:
            if group_by == "domain" and source == "history":
                return HybridHistorySearchEngine(db, embedder).aggregate(
                    group_by="domain",
                    filters=filters,
                    top_n=aggregate_top_n,
                )
            if group_by == "folder" and source == "bookmarks":
                return HybridBookmarkSearchEngine(db, embedder).aggregate(
                    group_by="folder",
                    filters=filters,
                    top_n=aggregate_top_n,
                )
            raise ValueError(
                f"group_by='{group_by}' is not supported for selected source '{source}'"
            )

        timing_ms = {}
        if source == "history":
            engine = HybridHistorySearchEngine(db, embedder)
            results, timing_ms, methods_executed = engine.search(
                query=query, methods=methods, filters=filters, top_k=top_k
            )
        else:
            engine = HybridBookmarkSearchEngine(db, embedder)
            results, timing_ms, methods_executed = engine.search(
                query=query, methods=methods, filters=filters, top_k=top_k
            )

    return {
        "results": results,
        "total_available": len(results),
        "methods_executed": methods_executed,
        "timing_ms": timing_ms,
        "error": None,
    }
