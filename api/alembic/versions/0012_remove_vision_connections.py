"""Remove per-user external vision API credentials."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_remove_vision_connections"
down_revision = "0011_archive_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("pkm_vision_connections")


def downgrade() -> None:
    op.create_table(
        "pkm_vision_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(160), nullable=False),
        sa.Column("credential_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("credential_key_id", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_vision_connection_user"),
    )
