"""add fulltext search tsvector columns

Revision ID: 003_fulltext
Revises: 002_unique
Create Date: 2026-02-11

Add search_tsv tsvector columns to history and bookmarks tables with GIN indexes.
Backfill from existing title + snippet + url. No embedding needed.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "003_fulltext"
down_revision: Union[str, Sequence[str], None] = "002_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_index_concurrently(connection: object, index_sql: str) -> None:
    """Run CREATE INDEX CONCURRENTLY outside a transaction (PostgreSQL requirement)."""
    engine = connection.engine
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as ac_conn:
        ac_conn.execute(text(index_sql))


def upgrade() -> None:
    # --- history ---
    op.execute("ALTER TABLE history ADD COLUMN search_tsv tsvector")

    op.execute("""
        UPDATE history
        SET search_tsv = to_tsvector('simple',
            COALESCE(title, '') || ' ' ||
            COALESCE(snippet, '') || ' ' ||
            COALESCE(domain, '') || ' ' ||
            COALESCE(url, '')
        )
    """)

    _create_index_concurrently(
        op.get_bind(),
        "CREATE INDEX CONCURRENTLY ix_history_search_tsv ON history USING GIN (search_tsv)",
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION history_search_tsv_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_tsv := to_tsvector('simple',
                COALESCE(NEW.title, '') || ' ' ||
                COALESCE(NEW.snippet, '') || ' ' ||
                COALESCE(NEW.domain, '') || ' ' ||
                COALESCE(NEW.url, '')
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_history_search_tsv
        BEFORE INSERT OR UPDATE OF title, snippet, domain, url
        ON history
        FOR EACH ROW
        EXECUTE FUNCTION history_search_tsv_update();
    """)

    # --- bookmarks ---
    op.execute("ALTER TABLE bookmarks ADD COLUMN search_tsv tsvector")

    op.execute("""
        UPDATE bookmarks
        SET search_tsv = to_tsvector('simple',
            COALESCE(title, '') || ' ' ||
            COALESCE(snippet, '') || ' ' ||
            COALESCE(folder, '') || ' ' ||
            COALESCE(url, '')
        )
    """)

    _create_index_concurrently(
        op.get_bind(),
        "CREATE INDEX CONCURRENTLY ix_bookmarks_search_tsv ON bookmarks USING GIN (search_tsv)",
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION bookmarks_search_tsv_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_tsv := to_tsvector('simple',
                COALESCE(NEW.title, '') || ' ' ||
                COALESCE(NEW.snippet, '') || ' ' ||
                COALESCE(NEW.folder, '') || ' ' ||
                COALESCE(NEW.url, '')
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_bookmarks_search_tsv
        BEFORE INSERT OR UPDATE OF title, snippet, folder, url
        ON bookmarks
        FOR EACH ROW
        EXECUTE FUNCTION bookmarks_search_tsv_update();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_bookmarks_search_tsv ON bookmarks")
    op.execute("DROP FUNCTION IF EXISTS bookmarks_search_tsv_update()")
    op.execute("DROP INDEX IF EXISTS ix_bookmarks_search_tsv")
    op.execute("ALTER TABLE bookmarks DROP COLUMN IF EXISTS search_tsv")

    op.execute("DROP TRIGGER IF EXISTS trg_history_search_tsv ON history")
    op.execute("DROP FUNCTION IF EXISTS history_search_tsv_update()")
    op.execute("DROP INDEX IF EXISTS ix_history_search_tsv")
    op.execute("ALTER TABLE history DROP COLUMN IF EXISTS search_tsv")
