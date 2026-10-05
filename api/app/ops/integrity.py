"""Read-only ownership and orphan checks for the intentionally FK-free schema."""

from sqlalchemy import text
from sqlalchemy.engine import Connection


CHECKS = {
    "sessions_without_account": "SELECT count(*) FROM pkm_user_sessions c LEFT JOIN pkm_accounts p ON p.id=c.user_id WHERE p.id IS NULL",
    "notebooks_without_account": "SELECT count(*) FROM pkm_notebooks c LEFT JOIN pkm_accounts p ON p.id=c.user_id WHERE p.id IS NULL",
    "tags_without_account": "SELECT count(*) FROM pkm_tags c LEFT JOIN pkm_accounts p ON p.id=c.user_id WHERE p.id IS NULL",
    "notes_without_account": "SELECT count(*) FROM pkm_notes c LEFT JOIN pkm_accounts p ON p.id=c.user_id WHERE p.id IS NULL",
    "notes_invalid_notebook": "SELECT count(*) FROM pkm_notes n LEFT JOIN pkm_notebooks b ON b.id=n.notebook_id AND b.user_id=n.user_id WHERE n.deleted_at IS NULL AND n.notebook_id IS NOT NULL AND (b.id IS NULL OR b.deleted_at IS NOT NULL)",
    "file_versions_without_account": "SELECT count(*) FROM pkm_note_file_versions c LEFT JOIN pkm_accounts p ON p.id=c.user_id WHERE p.id IS NULL",
    "file_versions_invalid_note": "SELECT count(*) FROM pkm_note_file_versions x LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id WHERE n.id IS NULL",
    "upload_sessions_without_account": "SELECT count(*) FROM pkm_file_upload_sessions c LEFT JOIN pkm_accounts p ON p.id=c.user_id WHERE p.id IS NULL",
    "upload_sessions_invalid_notebook": "SELECT count(*) FROM pkm_file_upload_sessions x LEFT JOIN pkm_notebooks n ON n.id=x.notebook_id AND n.user_id=x.user_id WHERE x.notebook_id IS NOT NULL AND (n.id IS NULL OR n.deleted_at IS NOT NULL)",
    "upload_sessions_invalid_note": "SELECT count(*) FROM pkm_file_upload_sessions x LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id WHERE x.note_id IS NOT NULL AND n.id IS NULL",
    "upload_sessions_invalid_duplicate_note": "SELECT count(*) FROM pkm_file_upload_sessions x LEFT JOIN pkm_notes n ON n.id=x.duplicate_note_id AND n.user_id=x.user_id WHERE x.duplicate_note_id IS NOT NULL AND n.id IS NULL",
    "ingest_jobs_without_account": "SELECT count(*) FROM pkm_file_ingest_jobs c LEFT JOIN pkm_accounts p ON p.id=c.user_id WHERE p.id IS NULL",
    "ingest_jobs_invalid_note": "SELECT count(*) FROM pkm_file_ingest_jobs x LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id WHERE n.id IS NULL",
    "ingest_jobs_invalid_file_version": "SELECT count(*) FROM pkm_file_ingest_jobs x LEFT JOIN pkm_note_file_versions f ON f.id=x.file_version_id AND f.note_id=x.note_id AND f.user_id=x.user_id WHERE f.id IS NULL",
    "link_drafts_without_account": "SELECT count(*) FROM pkm_link_drafts c LEFT JOIN pkm_accounts p ON p.id=c.user_id WHERE p.id IS NULL",
    "link_drafts_invalid_notebook": "SELECT count(*) FROM pkm_link_drafts x LEFT JOIN pkm_notebooks n ON n.id=x.notebook_id AND n.user_id=x.user_id WHERE x.notebook_id IS NOT NULL AND (n.id IS NULL OR n.deleted_at IS NOT NULL)",
    "text_blocks_invalid_note": "SELECT count(*) FROM pkm_note_text_blocks x LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id WHERE n.id IS NULL",
    "note_tags_invalid_note": "SELECT count(*) FROM pkm_note_tags x LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id WHERE n.id IS NULL",
    "note_tags_invalid_tag": "SELECT count(*) FROM pkm_note_tags x LEFT JOIN pkm_tags t ON t.id=x.tag_id AND t.user_id=x.user_id WHERE t.id IS NULL",
    "chunks_invalid_note": "SELECT count(*) FROM pkm_note_chunks x LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id WHERE n.id IS NULL",
    "jobs_invalid_note": "SELECT count(*) FROM pkm_index_jobs x LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id WHERE n.id IS NULL",
    "revisions_invalid_note": "SELECT count(*) FROM pkm_note_revisions x LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id WHERE n.id IS NULL",
    "audit_without_account": "SELECT count(*) FROM pkm_audit_events x LEFT JOIN pkm_accounts p ON p.id=x.user_id WHERE p.id IS NULL",
    "connections_without_account": "SELECT count(*) FROM pkm_model_connections x LEFT JOIN pkm_accounts p ON p.id=x.user_id WHERE p.id IS NULL",
    "assistant_conversations_without_account": "SELECT count(*) FROM pkm_assistant_conversations x LEFT JOIN pkm_accounts p ON p.id=x.user_id WHERE p.id IS NULL",
    "assistant_messages_invalid_conversation": "SELECT count(*) FROM pkm_assistant_messages x LEFT JOIN pkm_assistant_conversations c ON c.id=x.conversation_id AND c.user_id=x.user_id WHERE c.id IS NULL",
    "assistant_traces_without_account": "SELECT count(*) FROM pkm_assistant_traces x LEFT JOIN pkm_accounts p ON p.id=x.user_id WHERE p.id IS NULL",
    "digest_settings_without_account": "SELECT count(*) FROM pkm_digest_settings x LEFT JOIN pkm_accounts p ON p.id=x.user_id WHERE p.id IS NULL",
    "digest_runs_without_account": "SELECT count(*) FROM pkm_digest_runs x LEFT JOIN pkm_accounts p ON p.id=x.user_id WHERE p.id IS NULL",
    "digest_runs_invalid_note": "SELECT count(*) FROM pkm_digest_runs x LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id WHERE x.note_id IS NOT NULL AND n.id IS NULL",
    "reminders_without_account": "SELECT count(*) FROM pkm_note_reminders x LEFT JOIN pkm_accounts p ON p.id=x.user_id WHERE p.id IS NULL",
    "reminders_invalid_note": "SELECT count(*) FROM pkm_note_reminders x LEFT JOIN pkm_notes n ON n.id=x.note_id AND n.user_id=x.user_id WHERE x.note_id IS NOT NULL AND n.id IS NULL",
}


def integrity_counts(connection: Connection) -> dict[str, int]:
    return {name: connection.scalar(text(query)) for name, query in CHECKS.items()}
