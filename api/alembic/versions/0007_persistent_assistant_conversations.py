"""Persist account-scoped assistant conversations and retrieval messages.

Revision ID: 0007_assistant_conversations
Revises: 0006_coalesced_content_indexing
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_assistant_conversations"
down_revision = "0006_coalesced_content_indexing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pkm_assistant_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=120), server_default=sa.text("'新对话'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pkm_assistant_conversations_pkey"),
    )
    op.create_index(
        "ix_assistant_conversations_user_updated",
        "pkm_assistant_conversations",
        ["user_id", "updated_at", "id"],
    )

    op.create_table(
        "pkm_assistant_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.SmallInteger(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pkm_assistant_messages_pkey"),
    )
    op.create_index(
        "ix_assistant_messages_user_conversation_created",
        "pkm_assistant_messages",
        ["user_id", "conversation_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_messages_user_conversation_created", table_name="pkm_assistant_messages")
    op.drop_table("pkm_assistant_messages")
    op.drop_index("ix_assistant_conversations_user_updated", table_name="pkm_assistant_conversations")
    op.drop_table("pkm_assistant_conversations")
