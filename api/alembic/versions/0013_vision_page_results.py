"""Persist per-page vision results for resumable file ingestion."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_vision_page_results"
down_revision = "0012_remove_vision_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pkm_file_ingest_jobs",
        sa.Column(
            "vision_results",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("pkm_file_ingest_jobs", "vision_results")
