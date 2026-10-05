"""Add object-backed uploads, resumable sessions and asynchronous extraction."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_object_upload_ingest"
down_revision = "0009_m3_files_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pkm_note_file_versions", sa.Column("storage_backend", sa.String(24), server_default="filesystem", nullable=False))
    op.add_column("pkm_note_file_versions", sa.Column("extraction_status", sa.String(24), server_default="ready", nullable=False))
    op.add_column("pkm_note_file_versions", sa.Column("extraction_error", sa.String(500), nullable=True))
    op.add_column("pkm_note_file_versions", sa.Column("extraction_fingerprint", sa.String(64), nullable=True))

    op.create_table(
        "pkm_file_upload_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("extension", sa.String(16), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("expected_sha256", sa.String(64), nullable=False),
        sa.Column("convert_legacy", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("object_key", sa.String(80), nullable=False),
        sa.Column("multipart_id", sa.Text(), nullable=False),
        sa.Column("notebook_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(24), server_default="uploading", nullable=False),
        sa.Column("uploaded_parts", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("duplicate_note_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_file_upload_object_key"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_file_upload_user_idempotency"),
    )
    op.create_index("ix_file_upload_sessions_user_expiry", "pkm_file_upload_sessions", ["user_id", "expires_at"])
    op.create_index("ix_file_upload_sessions_status_expiry", "pkm_file_upload_sessions", ["status", "expires_at"])

    op.create_table(
        "pkm_file_ingest_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_version_id", name="uq_file_ingest_version"),
    )
    op.create_index("ix_file_ingest_jobs_status_available", "pkm_file_ingest_jobs", ["status", "available_at"])

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


def downgrade() -> None:
    op.drop_table("pkm_vision_connections")
    op.drop_index("ix_file_ingest_jobs_status_available", table_name="pkm_file_ingest_jobs")
    op.drop_table("pkm_file_ingest_jobs")
    op.drop_index("ix_file_upload_sessions_status_expiry", table_name="pkm_file_upload_sessions")
    op.drop_index("ix_file_upload_sessions_user_expiry", table_name="pkm_file_upload_sessions")
    op.drop_table("pkm_file_upload_sessions")
    op.drop_column("pkm_note_file_versions", "extraction_fingerprint")
    op.drop_column("pkm_note_file_versions", "extraction_error")
    op.drop_column("pkm_note_file_versions", "extraction_status")
    op.drop_column("pkm_note_file_versions", "storage_backend")
