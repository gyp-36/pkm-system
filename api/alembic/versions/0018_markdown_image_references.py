"""Track system image references from Markdown notes."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.knowledge.markdown_images import extract_image_references


revision = "0018_markdown_image_references"
down_revision = "0017_assistant_traces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pkm_markdown_image_references",
        sa.Column("markdown_note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("image_note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alt_text", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("markdown_note_id", "start_offset", name="pk_markdown_image_references"),
    )
    op.create_index(
        "ix_markdown_image_refs_image",
        "pkm_markdown_image_references",
        ["user_id", "image_note_id"],
    )
    op.create_index(
        "ix_markdown_image_refs_markdown",
        "pkm_markdown_image_references",
        ["user_id", "markdown_note_id"],
    )

    connection = op.get_bind()
    notes = connection.execute(sa.text(
        "SELECT id, user_id, body_md FROM pkm_notes "
        "WHERE content_kind IN ('markdown', 'md')"
    ))
    insert_reference = sa.text(
        "INSERT INTO pkm_markdown_image_references "
        "(markdown_note_id, start_offset, end_offset, user_id, image_note_id, alt_text) "
        "VALUES (:markdown_note_id, :start_offset, :end_offset, :user_id, :image_note_id, :alt_text)"
    )
    for note_id, user_id, body_md in notes:
        for reference in extract_image_references(body_md):
            connection.execute(insert_reference, {
                "markdown_note_id": note_id,
                "start_offset": reference.start,
                "end_offset": reference.end,
                "user_id": user_id,
                "image_note_id": reference.image_note_id,
                "alt_text": reference.alt_text,
            })


def downgrade() -> None:
    op.drop_index("ix_markdown_image_refs_markdown", table_name="pkm_markdown_image_references")
    op.drop_index("ix_markdown_image_refs_image", table_name="pkm_markdown_image_references")
    op.drop_table("pkm_markdown_image_references")
