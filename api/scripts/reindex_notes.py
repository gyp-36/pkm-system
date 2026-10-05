"""Queue current notes for rebuilding chunks with the active parser/indexer."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.models import FileIngestJob, Note, NoteFileVersion
from app.knowledge.notes import queue_index


def reindex_all_notes() -> tuple[int, int]:
    index_only_count = 0
    file_count = 0
    now = datetime.now(timezone.utc)

    with SessionLocal.begin() as db:
        notes = db.scalars(select(Note).where(Note.deleted_at.is_(None)).with_for_update()).all()
        for note in notes:
            latest_file = db.scalar(
                select(NoteFileVersion)
                .where(NoteFileVersion.note_id == note.id, NoteFileVersion.user_id == note.user_id)
                .order_by(NoteFileVersion.version.desc())
                .limit(1)
            )
            if latest_file is None or latest_file.extraction_status == "preserved" or latest_file.extension != "docx":
                queue_index(db, note)
                index_only_count += 1
                continue

            job = db.scalar(
                select(FileIngestJob)
                .where(FileIngestJob.file_version_id == latest_file.id)
                .with_for_update()
            )
            if job is None:
                job = FileIngestJob(
                    user_id=note.user_id,
                    note_id=note.id,
                    file_version_id=latest_file.id,
                    status="pending",
                    available_at=now,
                    created_at=now,
                    updated_at=now,
                )
                db.add(job)
            else:
                job.status = "pending"
                job.attempts = 0
                job.last_error = None
                job.available_at = now
                job.updated_at = now
            file_count += 1

    return index_only_count, file_count


if __name__ == "__main__":
    index_only_count, file_count = reindex_all_notes()
    print(f"Queued {index_only_count} notes for reindexing and {file_count} DOCX files for re-extraction.")
