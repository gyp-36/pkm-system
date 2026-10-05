"""Index asynchronous link draft fetch queue."""

from alembic import op


revision = "0013_link_draft_fetch_queue"
down_revision = "0012_remove_vision_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_link_drafts_fetch_queue", "pkm_link_drafts", ["fetch_status", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_link_drafts_fetch_queue", table_name="pkm_link_drafts")
