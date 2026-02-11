"""Lilith Browser MCP server: hybrid search over history and bookmarks."""

import json
import logging
import sys

from mcp.server.fastmcp import FastMCP

from core.config import settings
from core.database import db_session
from core.embeddings import Embedder
from mcp_server.hybrid_search import HybridBookmarkSearchEngine, HybridHistorySearchEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp_server")


def _create_mcp(host: str = "127.0.0.1", port: int = 8000) -> FastMCP:
    return FastMCP(
        "Lilith Browser",
        json_response=True,
        host=host,
        port=port,
    )


mcp = _create_mcp()


@mcp.tool()
def search_capabilities() -> dict:
    """Return this server's search capabilities: supported methods, filters, limits."""
    return {
        "schema_version": "1.0",
        "sources": [
            {
                "source_name": "browser_history",
                "source_class": "personal",
                "supported_methods": ["structured", "fulltext", "vector"],
                "supported_filters": [
                    {"name": "date_after", "type": "date", "operators": ["gte"], "description": "Visited on or after this date"},
                    {"name": "date_before", "type": "date", "operators": ["lte"], "description": "Visited on or before this date"},
                    {"name": "domain", "type": "string", "operators": ["contains"], "description": "Domain substring filter"},
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
                    {"name": "folder", "type": "string", "operators": ["contains"], "description": "Bookmark folder filter"},
                    {"name": "date_after", "type": "date", "operators": ["gte"], "description": "Bookmarked on or after this date"},
                    {"name": "date_before", "type": "date", "operators": ["lte"], "description": "Bookmarked on or before this date"},
                ],
                "max_limit": 100,
                "default_limit": 10,
                "sort_fields": ["added_at", "relevance"],
                "default_ranking": "vector",
            },
        ],
    }


@mcp.tool()
def unified_search(
    query: str = "",
    methods: list[str] | None = None,
    filters: list[dict] | None = None,
    top_k: int = 10,
    include_scores: bool = True,
    search_history: bool = True,
    search_bookmarks: bool = True,
) -> dict:
    """Hybrid search over browser history and bookmarks.

    Args:
        query: Semantic or keyword query. Empty for structured-only search.
        methods: Retrieval methods: 'structured', 'fulltext', 'vector'. None = auto-select.
        filters: Filter clauses: [{"field": "domain", "operator": "contains", "value": "github"}].
        top_k: Maximum results per sub-source (history/bookmarks).
        include_scores: Include per-method scores.
        search_history: Whether to search browser history.
        search_bookmarks: Whether to search bookmarks.

    Returns:
        {results: [...], total_available, methods_executed, timing_ms, error}
    """
    top_k = min(max(1, top_k), 100)
    all_results: list[dict] = []
    all_timing: dict[str, float] = {}
    all_methods: list[str] = []

    try:
        with db_session() as db:
            embedder = Embedder()

            if search_history:
                engine = HybridHistorySearchEngine(db, embedder)
                results, timing, methods_used = engine.search(
                    query=query, methods=methods, filters=filters, top_k=top_k,
                )
                all_results.extend(results)
                for k, v in timing.items():
                    all_timing[f"history_{k}"] = v
                for m in methods_used:
                    if m not in all_methods:
                        all_methods.append(m)

            if search_bookmarks:
                engine = HybridBookmarkSearchEngine(db, embedder)
                results, timing, methods_used = engine.search(
                    query=query, methods=methods, filters=filters, top_k=top_k,
                )
                all_results.extend(results)
                for k, v in timing.items():
                    all_timing[f"bookmarks_{k}"] = v
                for m in methods_used:
                    if m not in all_methods:
                        all_methods.append(m)

        # Sort combined results by fused score
        weights = {"structured": 1.0, "fulltext": 0.85, "vector": 0.7}

        def _fused_score(r: dict) -> float:
            scores = r.get("scores", {})
            if not scores:
                return 0.0
            total_w = sum(weights.get(m, 0.5) for m in scores)
            total_s = sum(scores[m] * weights.get(m, 0.5) for m in scores)
            return total_s / total_w if total_w > 0 else 0.0

        all_results.sort(key=_fused_score, reverse=True)

        return {
            "success": True,
            "output": json.dumps({
                "results": all_results[:top_k],
                "total_available": len(all_results),
                "methods_executed": all_methods,
                "timing_ms": all_timing,
                "error": None,
            }),
        }
    except Exception as e:
        logger.exception("unified_search failed")
        return {"success": False, "error": f"Search failed: {e!s}"}


@mcp.tool()
def email_get(email_id: str, account_id: int | None = None) -> dict:
    """Stub: not applicable for browser server."""
    return {"success": False, "error": "email_get is not available on this server"}


def main(transport: str = "stdio", port: int = 8001) -> int:
    if transport == "stdio":
        mcp.run(transport="stdio")
        return 0

    app = _create_mcp(host="0.0.0.0", port=port)
    app.tool()(search_capabilities)
    app.tool()(unified_search)
    import asyncio
    import uvicorn
    from contextlib import asynccontextmanager
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.routing import Mount

    starlette_app = app.streamable_http_app()
    session_manager = app.session_manager

    async def _rewrite_root_to_mcp(scope, receive, send):
        if scope.get("path") == "/":
            scope = {**scope, "path": "/mcp"}
        await starlette_app(scope, receive, send)

    @asynccontextmanager
    async def lifespan(asgi_app):
        async with session_manager.run():
            yield

    cors_app = Starlette(
        routes=[Mount("/", app=_rewrite_root_to_mcp)],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
                allow_headers=["*"],
                expose_headers=["*"],
            )
        ],
        lifespan=lifespan,
    )
    config = uvicorn.Config(
        cors_app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
    return 0
