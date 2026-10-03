"""Lifecycle timestamps, recoverable note revisions, and metadata-only audit events.

Revision ID: 0003_lifecycle_history_audit
Revises: 0002_chunk_source
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_lifecycle_history_audit"
down_revision = "0002_chunk_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("accounts", "notebooks", "tags"):
        op.add_column(table, sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
        op.execute(f"UPDATE {table} SET updated_at = created_at")
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("notes", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("user_sessions", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.add_column("user_sessions", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.add_column("note_tags", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.add_column("note_chunks", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))

    op.drop_constraint("uq_notebooks_user_name", "notebooks", type_="unique")
    op.drop_constraint("uq_tags_user_name", "tags", type_="unique")
    op.create_index("uq_notebooks_active_user_name", "notebooks", ["user_id", "name"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("uq_tags_active_user_name", "tags", ["user_id", "name"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_notes_active_user_updated", "notes", ["user_id", "updated_at", "id"], postgresql_where=sa.text("deleted_at IS NULL"))

    op.create_table(
        "note_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("notebook_id", postgresql.UUID(as_uuid=True)),
        sa.Column("tag_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["note_id", "user_id"], ["notes.id", "notes.user_id"], ondelete="CASCADE", name="fk_revisions_owned_note"),
        sa.UniqueConstraint("note_id", "version", name="uq_revision_note_version"),
    )
    op.create_index("ix_revisions_user_note_version", "note_revisions", ["user_id", "note_id", "version"])
    op.execute("""
        INSERT INTO note_revisions (id, user_id, note_id, version, title, body_md, notebook_id, tag_ids, created_at)
        SELECT gen_random_uuid(), n.user_id, n.id, n.version, n.title, n.body_md, n.notebook_id,
               ARRAY(SELECT nt.tag_id FROM note_tags nt WHERE nt.note_id = n.id AND nt.user_id = n.user_id ORDER BY nt.tag_id),
               n.updated_at
        FROM notes n
    """)

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_version", sa.Integer()),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_user_created", "audit_events", ["user_id", "created_at"])
    op.create_index("ix_audit_entity_created", "audit_events", ["entity_type", "entity_id", "created_at"])

    op.execute("""
        CREATE FUNCTION pkm_touch_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("accounts", "user_sessions", "notebooks", "tags"):
        op.execute(f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION pkm_touch_updated_at()")


def downgrade() -> None:
    for table in ("accounts", "user_sessions", "notebooks", "tags"):
        op.execute(f"DROP TRIGGER trg_{table}_updated_at ON {table}")
    op.execute("DROP FUNCTION pkm_touch_updated_at()")
    op.drop_table("audit_events")
    op.drop_table("note_revisions")
    op.drop_index("ix_notes_active_user_updated", table_name="notes")
    op.drop_index("uq_tags_active_user_name", table_name="tags")
    op.drop_index("uq_notebooks_active_user_name", table_name="notebooks")
    op.create_unique_constraint("uq_notebooks_user_name", "notebooks", ["user_id", "name"])
    op.create_unique_constraint("uq_tags_user_name", "tags", ["user_id", "name"])
    op.drop_column("note_chunks", "created_at")
    op.drop_column("note_tags", "created_at")
    op.drop_column("user_sessions", "updated_at")
    op.drop_column("user_sessions", "created_at")
    op.drop_column("notes", "deleted_at")
    for table in ("tags", "notebooks", "accounts"):
        op.drop_column(table, "deleted_at")
        op.drop_column(table, "updated_at")
