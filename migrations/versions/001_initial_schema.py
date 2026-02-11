"""initial_schema: history and bookmarks with pgvector and indexes.

Revision ID: 001_initial
Revises:
Create Date: 2026-02-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(253), nullable=True),
        sa.Column("last_visit_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("visit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("browser", sa.String(), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_history_domain", "history", ["domain"], unique=False)
    op.create_index("ix_history_last_visit_time", "history", [sa.desc("last_visit_time")], unique=False)
    op.execute(
        "CREATE INDEX ix_history_embedding ON history USING hnsw (embedding vector_cosine_ops)"
    )
    # Optional: op.create_unique_constraint("uq_history_url_browser", "history", ["url", "browser"])

    op.create_table(
        "bookmarks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("folder", sa.Text(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("browser", sa.String(), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bookmarks_folder", "bookmarks", ["folder"], unique=False)
    op.create_index("ix_bookmarks_added_at", "bookmarks", [sa.desc("added_at")], unique=False)
    op.execute(
        "CREATE INDEX ix_bookmarks_embedding ON bookmarks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_bookmarks_embedding", table_name="bookmarks")
    op.drop_index("ix_bookmarks_added_at", table_name="bookmarks")
    op.drop_index("ix_bookmarks_folder", table_name="bookmarks")
    op.drop_table("bookmarks")
    op.drop_index("ix_history_embedding", table_name="history")
    op.drop_index("ix_history_last_visit_time", table_name="history")
    op.drop_index("ix_history_domain", table_name="history")
    op.drop_table("history")
