"""Backfill image references for Markdown notes archived before indexing."""

from alembic import op
import sqlalchemy as sa

from app.knowledge.markdown_images import extract_image_references


revision = "0020_backfill_md_image_refs"
down_revision = "0019_note_digests_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    notes = connection.execute(sa.text(
        "SELECT id, user_id, body_md FROM pkm_notes "
        "WHERE content_kind IN ('markdown', 'md')"
    ))
    insert_reference = sa.text(
        "INSERT INTO pkm_markdown_image_references "
        "(markdown_note_id, start_offset, end_offset, user_id, image_note_id, alt_text) "
        "VALUES (:markdown_note_id, :start_offset, :end_offset, :user_id, :image_note_id, :alt_text) "
        "ON CONFLICT (markdown_note_id, start_offset) DO NOTHING"
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
    # The backfill only adds rows. Reverting it separately could remove references
    # that were created after upgrade, so the owning table migration handles cleanup.
    pass
