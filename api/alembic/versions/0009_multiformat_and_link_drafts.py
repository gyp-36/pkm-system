"""Add versioned file notes and link drafts.

Revision ID: 0009_m3_files_links
Revises: 0008_assistant_lifecycle
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_m3_files_links"
down_revision = "0008_assistant_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pkm_notes", sa.Column("content_kind", sa.String(16), server_default="markdown", nullable=False))
    op.add_column("pkm_notes", sa.Column("source_url", sa.Text(), nullable=True))
    op.create_table(
        "pkm_note_file_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("extension", sa.String(16), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=False),
        sa.Column("storage_key", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", "version", name="uq_note_file_version"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_note_file_user_note_version", "pkm_note_file_versions", ["user_id", "note_id", "version"])
    op.create_table(
        "pkm_link_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("snapshot_text", sa.Text(), server_default="", nullable=False),
        sa.Column("body_md", sa.Text(), server_default="", nullable=False),
        sa.Column("fetch_status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("fetch_error", sa.String(500), nullable=True),
        sa.Column("status", sa.String(24), server_default="draft", nullable=False),
        sa.Column("notebook_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_link_drafts_user_updated", "pkm_link_drafts", ["user_id", "updated_at"])
    op.create_index("uq_link_drafts_user_url", "pkm_link_drafts", ["user_id", "source_url"], unique=True, postgresql_where=sa.text("status <> 'published'"))
    op.add_column("pkm_note_chunks", sa.Column("location", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_table(
        "pkm_note_text_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("locator", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", "content_version", "ordinal", name="uq_text_block_position"),
    )
    op.create_index("ix_text_blocks_user_note_version", "pkm_note_text_blocks", ["user_id", "note_id", "content_version"])


def downgrade() -> None:
    op.drop_index("ix_text_blocks_user_note_version", table_name="pkm_note_text_blocks")
    op.drop_table("pkm_note_text_blocks")
    op.drop_column("pkm_note_chunks", "location")
    op.drop_index("uq_link_drafts_user_url", table_name="pkm_link_drafts")
    op.drop_index("ix_link_drafts_user_updated", table_name="pkm_link_drafts")
    op.drop_table("pkm_link_drafts")
    op.drop_index("ix_note_file_user_note_version", table_name="pkm_note_file_versions")
    op.drop_table("pkm_note_file_versions")
    op.drop_column("pkm_notes", "source_url")
    op.drop_column("pkm_notes", "content_kind")
