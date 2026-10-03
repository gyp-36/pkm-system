"""Add soft-delete lifecycle for assistant conversations.

Revision ID: 0008_assistant_lifecycle
Revises: 0007_assistant_conversations
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_assistant_lifecycle"
down_revision = "0007_assistant_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pkm_assistant_conversations", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("pkm_assistant_conversations", "deleted_at")
