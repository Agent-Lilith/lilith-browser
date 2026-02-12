import logging

from common.mcp import create_mcp_app, run_mcp_server

from mcp_server.tools import get_search_capabilities_tool, search_browser_unified_tool

logger = logging.getLogger("mcp_server")

mcp = create_mcp_app("Lilith Browser")


@mcp.tool()
def search_capabilities() -> dict:
    """Return browser search capabilities (history, bookmarks)."""
    return get_search_capabilities_tool()


@mcp.tool()
def unified_search(
    query: str = "",
    methods: list[str] | None = None,
    filters: list[dict] | None = None,
    top_k: int = 10,
    search_history: bool = True,
    search_bookmarks: bool = True,
) -> dict:
    """Hybrid search over browser history and bookmarks."""
    return search_browser_unified_tool(
        query=query,
        methods=methods,
        filters=filters,
        top_k=top_k,
        search_history=search_history,
        search_bookmarks=search_bookmarks,
    )


def main(transport: str = "stdio", port: int = 8001) -> None:
    run_mcp_server(mcp, transport=transport, port=port)
