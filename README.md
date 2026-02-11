# Lilith Browser

Ingest and store browser history and bookmarks (Vivaldi) in PostgreSQL; expose them via an MCP server for RAG.

## Quick start

### 1. Database (shared Postgres)

This project uses a **shared** PostgreSQL server. Database name for this app: `lilith_browser`.

Ensure the shared Postgres (with pgvector) is running. Clone the lilith-compose project first.

### 2. Run migrations

```bash
uv run alembic upgrade head
```

### 4. CLI Ingest

Reads `~/.config/vivaldi/Default/History` (SQLite) and `Bookmarks` (JSON) while Vivaldi can stay open (read-only, no lock).

```bash
uv run python main.py ingest
```

## MCP Server (Agent Tools)

The Lilith Browser MCP server.

```bash
uv run mcp
uv run mcp --transport streamable-http --port 6201
```

## Production: systemd timer

To run ingest periodically (e.g. every 15 minutes) under your user:

1. Run the new migration (adds unique constraints for upsert):
   ```bash
   uv run alembic upgrade head
   ```

2. Copy and edit the systemd units:
   ```bash
   mkdir -p ~/.config/systemd/user
   cp systemd/lilith-browser-ingest.service systemd/lilith-browser-ingest.timer ~/.config/systemd/user/
   # Edit the service: replace /path/to/lilith-browser with your project root in all three lines.
   ```

3. Enable and start the timer:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now lilith-browser-ingest.timer
   systemctl --user list-timers   # confirm it is scheduled
   ```

4. Optional: run embedding backfill on a slower schedule (e.g. daily) or manually after ingest.

### 8. MCP Tools

- `history_search` — Semantic search over history with optional date_after, date_before, domain; returns rank, url, title, snippet, score.
- `history_recent` — Recent visits by last_visit_time (optional domain filter).
- `bookmarks_search` — Semantic search over bookmarks with optional folder filter.
- `bookmarks_list` — List bookmarks by folder.
