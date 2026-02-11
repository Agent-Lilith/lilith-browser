"""Read Vivaldi (Chromium) History SQLite and Bookmarks JSON."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Chromium timestamp: microseconds since 1601-01-01 UTC.
# Unix epoch offset in seconds: 11644473600
CHROMIUM_EPOCH_OFFSET_SEC = 11_644_473_600


def _chromium_time_to_utc(microseconds: int | None) -> datetime | None:
    if microseconds is None or microseconds <= 0:
        return None
    unix_sec = (microseconds / 1_000_000) - CHROMIUM_EPOCH_OFFSET_SEC
    return datetime.fromtimestamp(unix_sec, tz=timezone.utc)


def _domain_from_url(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        return netloc.lower() if netloc else ""
    except Exception:
        return ""


def read_history(profile_dir: Path) -> list[dict]:
    """Read History SQLite; return list of dicts: url, title, last_visit_time, visit_count, domain."""
    history_path = profile_dir / "History"
    if not history_path.exists():
        raise FileNotFoundError(f"Vivaldi History not found at {history_path}")
    uri = f"file:{history_path}?mode=ro&nolock=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT url, title, visit_count, last_visit_time
            FROM urls
            WHERE url IS NOT NULL AND TRIM(url) != ''
            ORDER BY last_visit_time DESC
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        url = (r["url"] or "").strip()
        if not url:
            continue
        last_visit_time = _chromium_time_to_utc(r["last_visit_time"])
        out.append({
            "url": url,
            "title": (r["title"] or "").strip() or None,
            "last_visit_time": last_visit_time,
            "visit_count": r["visit_count"] or 0,
            "domain": _domain_from_url(url),
        })
    return out


def _walk_bookmarks(node: dict, folder_path: str) -> list[dict]:
    """Recursively collect bookmark nodes with url; folder_path is e.g. 'Bookmarks bar/Work'."""
    out = []
    title = (node.get("title") or "").strip() or ""

    if "url" in node:
        # Leaf bookmark
        url = (node.get("url") or "").strip()
        if url:
            date_added = node.get("date_added")
            if isinstance(date_added, str) and date_added.isdigit():
                date_added = int(date_added)
            added_at = None
            if isinstance(date_added, int):
                # Chromium Bookmarks often use microseconds since 1601; else ms since epoch
                if date_added > 1e12:
                    added_at = _chromium_time_to_utc(date_added)
                else:
                    try:
                        added_at = datetime.fromtimestamp(date_added / 1000.0, tz=timezone.utc)
                    except (ValueError, OSError):
                        pass
            out.append({
                "url": url,
                "title": title or None,
                "folder": folder_path or None,
                "added_at": added_at,
            })
        return out

    # Folder
    child_path = f"{folder_path}/{title}" if folder_path else title
    for child in node.get("children") or []:
        out.extend(_walk_bookmarks(child, child_path))
    return out


def read_bookmarks(profile_dir: Path) -> list[dict]:
    """Read Bookmarks JSON; return list of dicts: url, title, folder, added_at."""
    bookmarks_path = profile_dir / "Bookmarks"
    if not bookmarks_path.exists():
        raise FileNotFoundError(f"Vivaldi Bookmarks not found at {bookmarks_path}")
    try:
        data = bookmarks_path.read_text(encoding="utf-8", errors="replace")
        root = json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Bookmarks file invalid or busy: {e}") from e
    roots = root.get("roots") or {}
    out = []
    for key in ("bookmark_bar", "other", "synced"):
        node = roots.get(key)
        if not node:
            continue
        folder_name = "Bookmarks bar" if key == "bookmark_bar" else key.replace("_", " ").title()
        out.extend(_walk_bookmarks(node, folder_name))
    return out
