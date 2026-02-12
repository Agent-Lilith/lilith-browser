"""CLI entry for lilith-browser: migrate, ingest, mcp."""

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

console = Console(stderr=True)


def cmd_migrate(_args: argparse.Namespace) -> int:
    import alembic.config

    alembic.config.main(argv=["upgrade", "head"])
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    import logging

    from core.config import get_vivaldi_profile_path
    from core.database import db_session
    from core.embeddings import Embedder
    from ingest.sync import run_embedding_backfill, upsert_bookmarks, upsert_history
    from ingest.vivaldi_reader import read_bookmarks, read_history

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(console=console, show_path=False)],
    )
    logger = logging.getLogger("ingest")

    profile_dir = (
        Path(args.profile).expanduser().resolve()
        if args.profile
        else get_vivaldi_profile_path()
    )
    if not profile_dir.is_dir():
        console.print(f"[red]Profile directory not found: {profile_dir}[/red]")
        return 1

    if not args.history_only:
        try:
            bm = read_bookmarks(profile_dir)
            logger.info("Read %d bookmarks from %s", len(bm), profile_dir / "Bookmarks")
        except (FileNotFoundError, ValueError) as e:
            console.print(f"[red]{e}[/red]")
            return 1
    else:
        bm = []

    if not args.bookmarks_only:
        try:
            hist = read_history(profile_dir)
            logger.info(
                "Read %d history URLs from %s", len(hist), profile_dir / "History"
            )
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
            return 1
    else:
        hist = []

    if args.dry_run:
        console.print("[yellow]Dry run: skipping DB write and embed.[/yellow]")
        return 0

    with db_session() as db:
        if hist:
            upsert_history(db, hist)
            logger.info("Upserted %d history rows", len(hist))
        if bm:
            upsert_bookmarks(db, bm)
            logger.info("Upserted %d bookmark rows", len(bm))
        if not args.skip_embed and (hist or bm):
            embedder = Embedder()
            if embedder.endpoint_url:
                h_n, b_n = run_embedding_backfill(
                    db, embedder, batch_size=args.embed_batch_size
                )
                logger.info("Embedding backfill: %d history, %d bookmarks", h_n, b_n)
            else:
                logger.warning("EMBEDDING_URL not set; skipping embedding backfill")
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from mcp_server.server import main as mcp_main

    mcp_main(transport=args.transport, port=args.port)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="lilith-browser",
        description="Browser history and bookmarks for Lilith agent RAG. Commands: migrate | ingest | mcp.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    mig_p = sub.add_parser("migrate", help="Run DB migrations (alembic upgrade head)")
    mig_p.set_defaults(func=cmd_migrate)

    ingest_p = sub.add_parser(
        "ingest", help="Ingest from Vivaldi (history + bookmarks)"
    )
    ingest_p.add_argument(
        "--profile",
        metavar="PATH",
        help="Vivaldi profile directory (default: ~/.config/vivaldi/Default)",
    )
    ingest_p.add_argument(
        "--history-only", action="store_true", help="Ingest only history"
    )
    ingest_p.add_argument(
        "--bookmarks-only", action="store_true", help="Ingest only bookmarks"
    )
    ingest_p.add_argument(
        "--skip-embed",
        action="store_true",
        help="Do not run embedding backfill (faster for cron)",
    )
    ingest_p.add_argument(
        "--dry-run", action="store_true", help="Only read sources, do not write to DB"
    )
    ingest_p.add_argument(
        "--embed-batch-size",
        type=int,
        default=50,
        metavar="N",
        help="Batch size for embedding (default: 50)",
    )
    ingest_p.set_defaults(func=cmd_ingest)

    mcp_p = sub.add_parser("mcp", help="Run MCP server")
    mcp_p.add_argument(
        "--transport", choices=["stdio", "streamable-http"], default="stdio"
    )
    mcp_p.add_argument(
        "--port", type=int, default=8001, help="Port for streamable-http"
    )
    mcp_p.set_defaults(func=cmd_mcp)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
