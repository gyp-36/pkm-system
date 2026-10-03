"""Locate vector hits in either the title or Markdown body.

Revision ID: 0002_chunk_source
Revises: 0001_initial
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_chunk_source"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("note_chunks", sa.Column("source", sa.String(10), nullable=False, server_default="body"))
    op.alter_column("note_chunks", "source", server_default=None)


def downgrade() -> None:
    op.drop_column("note_chunks", "source")
