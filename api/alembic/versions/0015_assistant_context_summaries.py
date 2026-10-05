"""Persist compact context checkpoints for long assistant conversations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_assistant_context_summaries"
down_revision = "0014_merge_ingest_link_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pkm_assistant_conversations", sa.Column("context_summary", sa.Text(), nullable=True))
    op.add_column(
        "pkm_assistant_conversations",
        sa.Column("summary_through_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "pkm_assistant_conversations",
        sa.Column("summary_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pkm_assistant_conversations", "summary_updated_at")
    op.drop_column("pkm_assistant_conversations", "summary_through_message_id")
    op.drop_column("pkm_assistant_conversations", "context_summary")
