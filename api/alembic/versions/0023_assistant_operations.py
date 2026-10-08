"""Account-owned assistant grants and atomic operation receipts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0023_assistant_operations"
down_revision = "0022_audit_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Application rollback intentionally retains the ledger; re-upgrade is safe.
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("pkm_assistant_operations"):
        columns = {column["name"] for column in inspector.get_columns("pkm_assistant_operations")}
        expected = {"id", "user_id", "conversation_id", "request_id", "request_hash", "context_fingerprint", "status", "intent", "proposal", "receipt", "created_at", "expires_at"}
        if not expected <= columns:
            raise RuntimeError("Retained assistant operation schema is incomplete")
        return
    op.create_table("pkm_assistant_operations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", pg.UUID(as_uuid=True)),
        sa.Column("request_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("context_fingerprint", sa.String(64)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("intent", pg.JSONB(), nullable=False),
        sa.Column("proposal", pg.JSONB(), nullable=False),
        sa.Column("receipt", pg.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "request_id", name="uq_assistant_operation_request"))
    op.create_index("ix_assistant_operation_conversation", "pkm_assistant_operations", ["user_id", "conversation_id", "created_at"])
    op.create_index("ix_assistant_operation_expiry", "pkm_assistant_operations", ["expires_at"])


def downgrade() -> None:
    # Receipts must survive application rollback; do not destroy grants/history.
    pass
