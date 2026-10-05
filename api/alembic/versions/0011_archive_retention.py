"""为归档列表和到期清理增加索引。"""

from alembic import op
import sqlalchemy as sa


revision = "0011_archive_retention"
down_revision = "0010_object_upload_ingest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_notes_archive_user_deleted",
        "pkm_notes",
        ["user_id", "deleted_at", "id"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.create_index(
        "ix_notes_archive_deleted",
        "pkm_notes",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notes_archive_deleted", table_name="pkm_notes")
    op.drop_index("ix_notes_archive_user_deleted", table_name="pkm_notes")
