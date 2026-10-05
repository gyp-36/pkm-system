"""Persist redacted assistant execution traces for local debugging."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0017_assistant_traces"
down_revision = "0016_note_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pkm_assistant_traces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assistant_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entrypoint", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="running", nullable=False),
        sa.Column("error_type", sa.String(length=120), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pkm_assistant_traces_pkey"),
    )
    op.create_index("ix_assistant_traces_started", "pkm_assistant_traces", ["started_at", "id"])
    op.create_index(
        "ix_assistant_traces_entry_status_started",
        "pkm_assistant_traces",
        ["entrypoint", "status", "started_at"],
    )
    op.create_index(
        "ix_assistant_traces_conversation_message",
        "pkm_assistant_traces",
        ["conversation_id", "assistant_message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_traces_conversation_message", table_name="pkm_assistant_traces")
    op.drop_index("ix_assistant_traces_entry_status_started", table_name="pkm_assistant_traces")
    op.drop_index("ix_assistant_traces_started", table_name="pkm_assistant_traces")
    op.drop_table("pkm_assistant_traces")
