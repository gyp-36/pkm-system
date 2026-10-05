"""Prefix application tables, remove foreign keys, and store finite values as codes.

Revision ID: 0004_core_simplify
Revises: 0003_lifecycle_history_audit
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_core_simplify"
down_revision = "0003_lifecycle_history_audit"
branch_labels = None
depends_on = None


TABLES = (
    "accounts", "user_sessions", "notebooks", "tags", "notes", "note_tags",
    "note_chunks", "index_jobs", "note_revisions", "audit_events",
)

CODE_MAPS = {
    ("notes", "index_status"): {"pending": 1, "ready": 2, "error": 3},
    ("note_chunks", "source"): {"title": 1, "body": 2},
    ("index_jobs", "status"): {"pending": 1, "processing": 2, "done": 3, "stale": 4},
    ("audit_events", "actor_type"): {"user": 1, "system": 2},
    ("audit_events", "action"): {"register": 1, "login": 2, "logout": 3, "create": 4, "update": 5, "rename": 6, "delete": 7},
    ("audit_events", "entity_type"): {"account": 1, "session": 2, "note": 3, "notebook": 4, "tag": 5},
}

FOREIGN_KEYS = {
    "user_sessions": ("user_sessions_user_id_fkey",),
    "notebooks": ("notebooks_user_id_fkey",),
    "tags": ("tags_user_id_fkey",),
    "notes": ("fk_notes_owned_notebook", "notes_user_id_fkey"),
    "note_tags": ("fk_note_tags_owned_note", "fk_note_tags_owned_tag"),
    "note_chunks": ("fk_chunks_owned_note",),
    "index_jobs": ("fk_jobs_owned_note",),
    "note_revisions": ("fk_revisions_owned_note",),
    "audit_events": ("audit_events_user_id_fkey",),
}


def _convert(table: str, column: str, mapping: dict[str, int], *, reverse: bool = False) -> None:
    if reverse:
        cases = " ".join(f"WHEN {code} THEN '{name}'" for name, code in mapping.items())
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE varchar({40 if column in ('action', 'entity_type') else 10 if column == 'source' else 20}) USING CASE {column} {cases} END")
    else:
        cases = " ".join(f"WHEN '{name}' THEN {code}" for name, code in mapping.items())
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE smallint USING CASE {column} {cases} END")


def upgrade() -> None:
    connection = op.get_bind()
    for (table, column), mapping in CODE_MAPS.items():
        # 名称是固定的迁移常量；未知的历史值不能被转换为 NULL。
        values = set(connection.execute(sa.text(f"SELECT DISTINCT {column} FROM {table}")).scalars())
        unknown = values - mapping.keys()
        if unknown:
            raise RuntimeError(f"Unknown legacy values in {table}.{column}: {sorted(unknown)}")

    for table, names in FOREIGN_KEYS.items():
        for name in names:
            op.drop_constraint(name, table, type_="foreignkey")

    for table in TABLES:
        op.rename_table(table, f"pkm_{table}")

    for table in ("notebooks", "tags", "notes"):
        op.drop_constraint(f"uq_{table}_id_user", f"pkm_{table}", type_="unique")
    for table in ("notebooks", "tags"):
        op.drop_index(f"ix_{table}_user_id", table_name=f"pkm_{table}")
    op.drop_index("ix_notes_user_updated", table_name="pkm_notes")
    op.create_index("ix_notes_active_user_notebook_updated", "pkm_notes", ["user_id", "notebook_id", "updated_at", "id"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_note_tags_user_tag_note", "pkm_note_tags", ["user_id", "tag_id", "note_id"])

    for (table, column), mapping in CODE_MAPS.items():
        _convert(f"pkm_{table}", column, mapping)


def downgrade() -> None:
    for (table, column), mapping in CODE_MAPS.items():
        _convert(f"pkm_{table}", column, mapping, reverse=True)

    op.drop_index("ix_note_tags_user_tag_note", table_name="pkm_note_tags")
    op.drop_index("ix_notes_active_user_notebook_updated", table_name="pkm_notes")
    op.create_index("ix_notes_user_updated", "pkm_notes", ["user_id", "updated_at"])
    for table in ("notebooks", "tags"):
        op.create_index(f"ix_{table}_user_id", f"pkm_{table}", ["user_id"])
    for table in ("notebooks", "tags", "notes"):
        op.create_unique_constraint(f"uq_{table}_id_user", f"pkm_{table}", ["id", "user_id"])

    for table in reversed(TABLES):
        op.rename_table(f"pkm_{table}", table)

    for table in ("user_sessions", "notebooks", "tags", "notes", "audit_events"):
        op.create_foreign_key(f"{table}_user_id_fkey", table, "accounts", ["user_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_notes_owned_notebook", "notes", "notebooks", ["notebook_id", "user_id"], ["id", "user_id"])
    op.create_foreign_key("fk_note_tags_owned_note", "note_tags", "notes", ["note_id", "user_id"], ["id", "user_id"], ondelete="CASCADE")
    op.create_foreign_key("fk_note_tags_owned_tag", "note_tags", "tags", ["tag_id", "user_id"], ["id", "user_id"], ondelete="CASCADE")
    for table, name in (("note_chunks", "fk_chunks_owned_note"), ("index_jobs", "fk_jobs_owned_note"), ("note_revisions", "fk_revisions_owned_note")):
        op.create_foreign_key(name, table, "notes", ["note_id", "user_id"], ["id", "user_id"], ondelete="CASCADE")
