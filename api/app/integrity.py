"""Read-only ownership and orphan checks for the intentionally FK-free schema."""

from sqlalchemy import text
from sqlalchemy.engine import Connection


CHECKS = {
    "sessions_without_account": "SELECT count(*) FROM pkm_user_sessions c LEFT JOIN pkm_accounts p ON p.id=c.user_id WHERE p.id IS NULL",
    "notebooks_without_account": "SELECT count(*) FROM pkm_notebooks c LEFT JOIN pkm_accounts p ON p.id=c.user_id WHERE p.id IS NULL",
    "tags_without_account": "SELECT count(*) FROM pkm_tags c LEFT JOIN pkm_accounts p ON p.id=c.user_id WHERE p.id IS NULL",
    "notes_without_account": "SELECT count(*) FROM pkm_notes c LEFT JOIN pkm_accounts p ON p.id=c.user_id WHERE p.id IS NULL",
    "notes_invalid_notebook": "SELECT count(*) FROM pkm_notes n LEFT JOIN pkm_notebooks b ON b.id=n.notebook_id AND b.user_id=n.user_id WHERE n.deleted_at IS NULL AND n.notebook_id IS NOT NULL AND (b.id IS NULL OR b.deleted_at IS NOT NULL)",
    "note_tags_invalid_note": "SELECT count(*) FROM pkm_note_tags x LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id WHERE n.id IS NULL",
    "note_tags_invalid_tag": "SELECT count(*) FROM pkm_note_tags x LEFT JOIN pkm_tags t ON t.id=x.tag_id AND t.user_id=x.user_id WHERE t.id IS NULL",
    "chunks_invalid_note": "SELECT count(*) FROM pkm_note_chunks x LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id WHERE n.id IS NULL",
    "jobs_invalid_note": "SELECT count(*) FROM pkm_index_jobs x LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id WHERE n.id IS NULL",
    "revisions_invalid_note": "SELECT count(*) FROM pkm_note_revisions x LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id WHERE n.id IS NULL",
    "audit_without_account": "SELECT count(*) FROM pkm_audit_events x LEFT JOIN pkm_accounts p ON p.id=x.user_id WHERE p.id IS NULL",
    "connections_without_account": "SELECT count(*) FROM pkm_model_connections x LEFT JOIN pkm_accounts p ON p.id=x.user_id WHERE p.id IS NULL",
    "assistant_conversations_without_account": "SELECT count(*) FROM pkm_assistant_conversations x LEFT JOIN pkm_accounts p ON p.id=x.user_id WHERE p.id IS NULL",
    "assistant_messages_invalid_conversation": "SELECT count(*) FROM pkm_assistant_messages x LEFT JOIN pkm_assistant_conversations c ON c.id=x.conversation_id AND c.user_id=x.user_id WHERE c.id IS NULL",
}


def integrity_counts(connection: Connection) -> dict[str, int]:
    return {name: connection.scalar(text(query)) for name, query in CHECKS.items()}
