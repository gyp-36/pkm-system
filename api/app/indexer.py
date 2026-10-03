"""Versioned index queue processing and exact Unicode source offsets."""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select, text

from app.db import SessionLocal
from app.embeddings import embed
from app.enums import ChunkSource, IndexJobStatus, NoteIndexStatus
from app.models import IndexJob, Note, NoteChunk


@dataclass(frozen=True)
class Segment:
    source: ChunkSource
    start: int
    end: int
    content: str


def split_segment(source: ChunkSource, raw: str, start: int, end: int) -> list[Segment]:
    while start < end and raw[start].isspace():
        start += 1
    while end > start and raw[end - 1].isspace():
        end -= 1
    result = []
    while start < end:
        stop = min(end, start + 480)
        if stop < end:
            candidates = [raw.rfind(mark, start + 300, stop) for mark in ("。", "！", "？", "\n", "；", " ")]
            best = max(candidates)
            if best > start:
                stop = best + 1
        result.append(Segment(source, start, stop, raw[start:stop]))
        start = stop
        while start < end and raw[start].isspace():
            start += 1
    return result


def segment_note(title: str, body: str) -> list[Segment]:
    result = [Segment(ChunkSource.TITLE, 0, len(title), title)]
    start = 0
    for gap in re.finditer(r"\n[ \t]*\n", body):
        result.extend(split_segment(ChunkSource.BODY, body, start, gap.start()))
        start = gap.end()
    result.extend(split_segment(ChunkSource.BODY, body, start, len(body)))
    return result


def claim_job() -> uuid.UUID | None:
    with SessionLocal.begin() as db:
        reclaim_after = func.now() - text("interval '3 minutes'")
        job = db.scalar(
            select(IndexJob)
            .where(
                or_(
                    (IndexJob.status == IndexJobStatus.PENDING) & (IndexJob.available_at <= func.now()),
                    (IndexJob.status == IndexJobStatus.PROCESSING) & (IndexJob.updated_at < reclaim_after),
                )
            )
            .order_by(IndexJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.status = IndexJobStatus.PROCESSING
        job.updated_at = datetime.now(timezone.utc)
        return job.id


def refresh_job_lease(job_id: uuid.UUID, target_version: int) -> bool:
    with SessionLocal.begin() as db:
        job = db.scalar(select(IndexJob).where(IndexJob.id == job_id).with_for_update())
        if job is None or job.status != IndexJobStatus.PROCESSING or job.target_version != target_version:
            return False
        job.updated_at = datetime.now(timezone.utc)
        return True


def process_job(job_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        job = db.get(IndexJob, job_id)
        if job is None or job.status != IndexJobStatus.PROCESSING:
            return
        note = db.scalar(select(Note).where(Note.id == job.note_id, Note.user_id == job.user_id))
        target_version = job.target_version
        if note is None or note.deleted_at is not None or note.content_version != target_version:
            # Do not stale a job that a concurrent save has already retargeted.
            db.refresh(job, attribute_names=["status", "target_version"])
            if job.status == IndexJobStatus.PROCESSING and job.target_version == target_version:
                job.status = IndexJobStatus.STALE
                job.updated_at = datetime.now(timezone.utc)
            db.commit()
            return
        version = note.content_version
        title, body = note.title, note.body_md

    segments = segment_note(title, body)
    vectors = []
    for start in range(0, len(segments), 8):
        group = segments[start : start + 8]
        vectors.extend(embed([f"{title}\n{segment.content}" if segment.source == ChunkSource.BODY else segment.content for segment in group]))
        # Keep long-running embedding batches leased and stop if a newer edit
        # has already replaced this job's target version.
        if not refresh_job_lease(job_id, target_version):
            return

    with SessionLocal.begin() as db:
        job_ref = db.get(IndexJob, job_id)
        if job_ref is None:
            return
        # Match the note-before-job lock order used by note updates to avoid a
        # deadlock between the worker committing and an editor saving.
        note = db.scalar(
            select(Note)
            .where(Note.id == job_ref.note_id, Note.user_id == job_ref.user_id)
            .with_for_update()
        )
        job = db.scalar(select(IndexJob).where(IndexJob.id == job_id).with_for_update())
        if job is None or job.status != IndexJobStatus.PROCESSING or job.target_version != target_version:
            return
        if note is None or note.deleted_at is not None or note.content_version != version:
            job.status = IndexJobStatus.STALE
            job.updated_at = datetime.now(timezone.utc)
            return
        db.execute(delete(NoteChunk).where(NoteChunk.note_id == note.id, NoteChunk.user_id == note.user_id))
        db.add_all(
            NoteChunk(
                user_id=note.user_id,
                note_id=note.id,
                note_version=version,
                ordinal=ordinal,
                source=segment.source,
                start_offset=segment.start,
                end_offset=segment.end,
                content=segment.content,
                embedding=vector,
            )
            for ordinal, (segment, vector) in enumerate(zip(segments, vectors, strict=True))
        )
        note.index_status = NoteIndexStatus.READY
        job.status = IndexJobStatus.DONE
        job.last_error = None
        job.updated_at = datetime.now(timezone.utc)


def retry_job(job_id: uuid.UUID, message: str) -> None:
    with SessionLocal.begin() as db:
        job = db.scalar(select(IndexJob).where(IndexJob.id == job_id).with_for_update())
        if job is None or job.status != IndexJobStatus.PROCESSING:
            return
        now = datetime.now(timezone.utc)
        job.status = IndexJobStatus.PENDING
        job.attempts += 1
        job.last_error = message[:500]
        delay = min(900, 10 * (2 ** min(job.attempts - 1, 7)))
        job.available_at = now + timedelta(seconds=delay)
        job.updated_at = now
        note = db.scalar(select(Note).where(Note.id == job.note_id, Note.user_id == job.user_id))
        if note is not None and note.deleted_at is None and note.content_version == job.target_version:
            note.index_status = NoteIndexStatus.ERROR
