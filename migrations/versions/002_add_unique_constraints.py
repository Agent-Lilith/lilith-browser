"""add_unique_constraints for ingest upsert.

Revision ID: 002_unique
Revises: 001_initial
Create Date: 2026-02-10

"""
from typing import Sequence, Union

from alembic import op

revision: str = "002_unique"
down_revision: Union[str, Sequence[str], None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Deduplicate before adding constraints (in case ingest was run before this migration).
    # history: keep one row per (url, browser) with largest id (NULL = NULL for browser)
    op.execute("""
        DELETE FROM history a
        USING history b
        WHERE a.url = b.url AND a.browser IS NOT DISTINCT FROM b.browser
          AND a.id < b.id
    """)
    # bookmarks: keep one row per (url, folder, browser) with largest id
    op.execute("""
        DELETE FROM bookmarks a
        USING bookmarks b
        WHERE a.url = b.url
          AND COALESCE(a.folder, '') = COALESCE(b.folder, '')
          AND COALESCE(a.browser, '') = COALESCE(b.browser, '')
          AND a.id < b.id
    """)
    # Index on full url can exceed PostgreSQL B-tree limit (8191 bytes). Use digest(url) for uniqueness.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    # history: one row per (url, browser) via digest(url)
    op.execute(
        "CREATE UNIQUE INDEX uq_history_url_browser ON history (digest(url, 'sha256'), browser)"
    )
    # bookmarks: one row per (url, folder, browser); treat NULL folder/browser as '' for key
    op.execute(
        "CREATE UNIQUE INDEX uq_bookmarks_url_folder_browser ON bookmarks (digest(url, 'sha256'), COALESCE(folder, ''), COALESCE(browser, ''))"
    )


def downgrade() -> None:
    op.drop_index("uq_history_url_browser", table_name="history")
    op.drop_index("uq_bookmarks_url_folder_browser", table_name="bookmarks")
