"""Scheduled note digests and note-owned reminders."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0019_note_digests_reminders"
down_revision = "0018_markdown_image_references"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pkm_digest_settings",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("daily_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("daily_time", sa.String(5), nullable=False, server_default="21:00"),
        sa.Column("daily_next_at", sa.DateTime(timezone=True)),
        sa.Column("weekly_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("weekly_weekday", sa.SmallInteger(), nullable=False, server_default="6"),
        sa.Column("weekly_time", sa.String(5), nullable=False, server_default="21:00"),
        sa.Column("weekly_next_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "pkm_digest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("slot_key", sa.String(16), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("note_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_refs", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("error", sa.String(500)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "kind", "slot_key", name="uq_digest_user_kind_slot"),
    )
    op.create_index("ix_digest_runs_status_scheduled", "pkm_digest_runs", ["status", "scheduled_at"])
    op.create_index("ix_digest_runs_user_created", "pkm_digest_runs", ["user_id", "created_at"])
    op.create_table(
        "pkm_note_reminders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.String(200), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_note_reminders_user_status_due", "pkm_note_reminders", ["user_id", "status", "due_at"])
    op.create_index("ix_note_reminders_user_note", "pkm_note_reminders", ["user_id", "note_id"])


def downgrade() -> None:
    op.drop_index("ix_note_reminders_user_note", table_name="pkm_note_reminders")
    op.drop_index("ix_note_reminders_user_status_due", table_name="pkm_note_reminders")
    op.drop_table("pkm_note_reminders")
    op.drop_index("ix_digest_runs_user_created", table_name="pkm_digest_runs")
    op.drop_index("ix_digest_runs_status_scheduled", table_name="pkm_digest_runs")
    op.drop_table("pkm_digest_runs")
    op.drop_table("pkm_digest_settings")
