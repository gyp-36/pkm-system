"""Conversation-only memory, source-backed content and summary coverage."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0024_conversation_memory"
down_revision = "0023_assistant_operations"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "summary_metadata" not in {c["name"] for c in inspector.get_columns("pkm_assistant_conversations")}:
        op.add_column("pkm_assistant_conversations", sa.Column("summary_metadata", pg.JSONB()))
    if not inspector.has_table("pkm_assistant_memories"):
        op.create_table("pkm_assistant_memories",
            sa.Column("conversation_id", pg.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("transcript_hash", sa.String(64), nullable=False),
            sa.Column("through_message_id", pg.UUID(as_uuid=True)),
            sa.Column("state", pg.JSONB(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
        op.create_index("ix_assistant_memories_user", "pkm_assistant_memories", ["user_id", "conversation_id"])
    if not inspector.has_table("pkm_assistant_artifacts"):
        op.create_table("pkm_assistant_artifacts",
            sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
            sa.Column("conversation_id", pg.UUID(as_uuid=True), nullable=False),
            sa.Column("source_message_id", pg.UUID(as_uuid=True), nullable=False),
            sa.Column("kind", sa.String(24), nullable=False),
            sa.Column("label", sa.String(120), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("digest", sa.String(64), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("completeness", sa.String(16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("conversation_id", "source_message_id", "label", name="uq_assistant_artifact_source"))
        op.create_index("ix_assistant_artifacts_scope", "pkm_assistant_artifacts", ["user_id", "conversation_id", "created_at"])


def downgrade():
    # Additive data stays available across application rollback and re-upgrade.
    pass
