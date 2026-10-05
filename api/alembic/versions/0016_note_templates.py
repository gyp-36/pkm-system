"""Add account-owned Markdown note templates."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_note_templates"
down_revision = "0015_assistant_context_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pkm_note_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("body_md", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_note_templates_user_name", "pkm_note_templates", ["user_id", "name"], unique=True)
    op.create_index("ix_note_templates_user_updated", "pkm_note_templates", ["user_id", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_note_templates_user_updated", table_name="pkm_note_templates")
    op.drop_index("uq_note_templates_user_name", table_name="pkm_note_templates")
    op.drop_table("pkm_note_templates")
