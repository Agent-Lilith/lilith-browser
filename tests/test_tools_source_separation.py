import contextlib
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "lilith-core"))

from mcp_server import tools


def test_unified_search_rejects_both_sources_enabled():
    with pytest.raises(ValueError, match="Exactly one browser source"):
        tools.search_browser_unified_tool(
            query="test",
            search_history=True,
            search_bookmarks=True,
        )


def test_unified_search_rejects_no_source_enabled():
    with pytest.raises(ValueError, match="Exactly one browser source"):
        tools.search_browser_unified_tool(
            query="test",
            search_history=False,
            search_bookmarks=False,
        )


def test_unified_search_history_only(monkeypatch):
    class DummyEngine:
        def __init__(self, db, embedder):  # noqa: ARG002
            pass

        def search(self, query="", methods=None, filters=None, top_k=10):  # noqa: ARG002
            return (
                [{"id": "1", "source": "browser_history", "scores": {"vector": 0.8}}],
                {"total": 1.0},
                ["vector"],
            )

    monkeypatch.setattr(tools, "db_session", lambda: contextlib.nullcontext(object()))
    monkeypatch.setattr(tools, "Embedder", lambda: object())
    monkeypatch.setattr(tools, "HybridHistorySearchEngine", DummyEngine)

    out = tools.search_browser_unified_tool(
        query="test",
        search_history=True,
        search_bookmarks=False,
    )
    assert out["results"]
    assert out["results"][0]["source"] == "browser_history"
