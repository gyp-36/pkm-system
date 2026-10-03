"""One encrypted, user-owned active chat model connection.

Revision ID: 0005_model_connections
Revises: 0004_core_simplify
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_model_connections"
down_revision = "0004_core_simplify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pkm_model_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.SmallInteger(), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("base_url", sa.Text()),
        sa.Column("credential_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("credential_key_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "uq_model_connections_active_user", "pkm_model_connections", ["user_id"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute("CREATE TRIGGER trg_model_connections_updated_at BEFORE UPDATE ON pkm_model_connections FOR EACH ROW EXECUTE FUNCTION pkm_touch_updated_at()")


def downgrade() -> None:
    op.drop_table("pkm_model_connections")
