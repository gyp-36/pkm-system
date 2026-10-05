"""Versioned index queue processing and exact Unicode source offsets."""

import uuid
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select, text

from app.core.db import SessionLocal
from app.core.enums import ChunkSource, IndexJobStatus, NoteIndexStatus
from app.core.models import IndexJob, Note, NoteChunk, NoteTextBlock
from app.knowledge.chunking import Segment, segment_note
from app.knowledge.embeddings import embed
from app.knowledge.markdown_images import context_for_range, descriptions_for_references, reference_rows

log = logging.getLogger(__name__)


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
        now = datetime.now(timezone.utc)
        job.updated_at = now
        log.info(
            "index_job_claimed job=%s queue_wait_seconds=%.3f attempts=%s",
            job.id, max(0.0, (now - job.created_at).total_seconds()), job.attempts,
        )
        return job.id


def refresh_job_lease(job_id: uuid.UUID, target_version: int) -> bool:
    with SessionLocal.begin() as db:
        job = db.scalar(select(IndexJob).where(IndexJob.id == job_id).with_for_update())
        if job is None or job.status != IndexJobStatus.PROCESSING or job.target_version != target_version:
            return False
        job.updated_at = datetime.now(timezone.utc)
        return True


def process_job(job_id: uuid.UUID) -> None:
    started_at = time.monotonic()
    with SessionLocal() as db:
        job = db.get(IndexJob, job_id)
        if job is None or job.status != IndexJobStatus.PROCESSING:
            log.info("index_job_skipped request_id=%s reason=not_claimed", job_id)
            return
        note = db.scalar(select(Note).where(Note.id == job.note_id, Note.user_id == job.user_id))
        target_version = job.target_version
        if note is None or note.deleted_at is not None or note.content_version != target_version:
            # 如果并发保存已将任务指向新内容，不要把该任务标记为过期。
            db.refresh(job, attribute_names=["status", "target_version"])
            if job.status == IndexJobStatus.PROCESSING and job.target_version == target_version:
                job.status = IndexJobStatus.STALE
                job.updated_at = datetime.now(timezone.utc)
                reason = "stale"
            else:
                reason = "superseded"
            note_id_value = job.note_id
            db.commit()
            log.info("index_job_skipped request_id=%s reason=%s note=%s", job_id, reason, note_id_value)
            return
        version = note.content_version
        title, body = note.title, note.body_md
        text_blocks = db.scalars(select(NoteTextBlock).where(NoteTextBlock.note_id == note.id, NoteTextBlock.user_id == note.user_id, NoteTextBlock.content_version == version).order_by(NoteTextBlock.ordinal)).all()
        image_references = reference_rows(db, note.user_id, note.id) if note.content_kind in {"markdown", "md"} else []
        image_descriptions = descriptions_for_references(db, note.user_id, image_references)

    segments = segment_note(title, body, text_blocks)
    vectors = []
    for start in range(0, len(segments), 8):
        group = segments[start : start + 8]
        texts = []
        for segment in group:
            if segment.source != ChunkSource.BODY:
                texts.append(segment.content)
                continue
            parts = [title]
            if segment.context_prefix:
                parts.append(segment.context_prefix)
            parts.append(segment.content)
            image_context = context_for_range(image_references, image_descriptions, segment.start, segment.end)
            if image_context:
                parts.append(image_context)
            texts.append("\n".join(parts))
        vectors.extend(embed(texts))
        # 为耗时较长的向量批次续租；如果较新的编辑已替换任务目标版本，则停止处理。
        if not refresh_job_lease(job_id, target_version):
            return

    with SessionLocal.begin() as db:
        job_ref = db.get(IndexJob, job_id)
        if job_ref is None:
            return
        # 遵循笔记更新时先锁笔记再锁任务的顺序，避免 worker 提交与编辑器保存之间发生死锁。
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
            log.info("index_job_skipped request_id=%s reason=stale_before_commit note=%s", job_id, job_ref.note_id)
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
                location=segment.location,
                embedding=vector,
            )
            for ordinal, (segment, vector) in enumerate(zip(segments, vectors, strict=True))
        )
        note.index_status = NoteIndexStatus.READY
        job.status = IndexJobStatus.DONE
        job.last_error = None
        job.updated_at = datetime.now(timezone.utc)
        indexed_chunks = len(segments)
        indexed_note_id = note.id

    log.info(
        "index_job_finished request_id=%s note=%s version=%s chunks=%s elapsed_seconds=%.3f",
        job_id, indexed_note_id, version, indexed_chunks, time.monotonic() - started_at,
    )


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
        # 重试日志是判断「索引持续失败」的唯一线索，必须带上次数与下次可用时间。
        log.warning(
            "index_job_retry request_id=%s attempts=%s retry_in_seconds=%s error=%s",
            job_id, job.attempts, delay, message[:200],
        )
