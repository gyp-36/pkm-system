"""Allow standalone reminders alongside note-linked reminders."""

from alembic import op
import sqlalchemy as sa


revision = "0021_optional_reminder_note"
down_revision = "0020_backfill_md_image_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("pkm_note_reminders", "note_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    op.alter_column("pkm_note_reminders", "note_id", existing_type=sa.UUID(), nullable=False)
