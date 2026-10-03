"""Debounce and coalesce content indexing per note.

Revision ID: 0006_coalesced_content_indexing
Revises: 0005_model_connections
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_coalesced_content_indexing"
down_revision = "0005_model_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pkm_notes",
        sa.Column("content_version", sa.Integer(), nullable=True),
    )
    op.execute("UPDATE pkm_notes SET content_version = version")
    op.alter_column("pkm_notes", "content_version", nullable=False)

    op.add_column(
        "pkm_index_jobs",
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Keep the latest active version for each note before enforcing one active
    # job per note. Historical completed/stale rows remain available for audit.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY note_id
                       ORDER BY target_version DESC, updated_at DESC, created_at DESC, id DESC
                   ) AS position
            FROM pkm_index_jobs
            WHERE status IN (1, 2)
        )
        UPDATE pkm_index_jobs AS jobs
        SET status = 4, updated_at = now()
        FROM ranked
        WHERE jobs.id = ranked.id AND ranked.position > 1
        """
    )
    op.drop_constraint("uq_job_note_version", "pkm_index_jobs", type_="unique")
    op.create_index(
        "uq_jobs_active_note",
        "pkm_index_jobs",
        ["note_id"],
        unique=True,
        postgresql_where=sa.text("status IN (1, 2)"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_active_note", table_name="pkm_index_jobs")
    op.create_unique_constraint(
        "uq_job_note_version", "pkm_index_jobs", ["note_id", "target_version"]
    )
    op.drop_column("pkm_index_jobs", "available_at")
    op.drop_column("pkm_notes", "content_version")
