"""Durable file extraction, image description and current-version publication."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

import pypdfium2 as pdfium
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import func, or_, select, text

from app.core.db import SessionLocal
from app.core.enums import NoteIndexStatus
from app.core.models import FileIngestJob, Note, NoteFileVersion, NoteTextBlock
from app.knowledge.text_safety import sanitize_extracted_text
from app.knowledge.file_types import IMAGE_MIME_BY_EXT, IMAGE_EXTENSIONS

log = logging.getLogger(__name__)


def _append(pieces: list[str], blocks: list[tuple[int, int, dict]], value: str, locator: dict) -> None:
    value = sanitize_extracted_text(value.strip())
    if not value:
        return
    cursor = blocks[-1][1] if blocks else 0
    if pieces:
        pieces.append("\n\n")
        cursor += 2
    pieces.append(value)
    blocks.append((cursor, cursor + len(value), locator))


def extract_file(
    extension: str,
    content: bytes,
    db,
    user_id: uuid.UUID,
    vision_results: dict[str, dict] | None = None,
    save_vision_result: Callable[[int, str, str], None] | None = None,
) -> tuple[str, list[tuple[int, int, dict]], str]:
    from pypdf import PdfReader
    from app.knowledge.m3 import extract_text
    from app.knowledge.vision import describe_image_bytes

    vision_results = vision_results or {}

    def describe(page_number: int, image_bytes: bytes, media_type: str) -> tuple[str, bool]:
        cached = vision_results.get(str(page_number), {})
        if cached.get("status") == "ready" and cached.get("caption"):
            return str(cached["caption"]), False
        try:
            result = describe_image_bytes(image_bytes, media_type, db, user_id)
            caption = str(result.get("caption", ""))
            status = "ready" if result.get("status") == "ready" and caption else "empty"
            if save_vision_result:
                save_vision_result(page_number, caption, status)
            return caption, status != "ready"
        except Exception:
            log.warning("file_vision_page_failed page=%s", page_number)
            if save_vision_result:
                save_vision_result(page_number, "", "failed")
            return "", True

    if extension in IMAGE_EXTENSIONS:
        caption, caption_failed = describe(1, content, IMAGE_MIME_BY_EXT[extension])
        text_value = sanitize_extracted_text(f"图像描述：{caption}") if caption else ""
        blocks = [(0, len(text_value), {"kind": "image", "source": "vision"})] if text_value else []
        status = ("partial" if text_value else "needs_vision") if caption_failed else "ready"
        return text_value, blocks, status

    if extension != "pdf":
        body, blocks = extract_text(extension, content)
        status = "ready" if body.strip() else "unsupported"
        return body, blocks, status

    pdf = PdfReader(io.BytesIO(content), strict=False)
    rendered = pdfium.PdfDocument(content)
    pieces: list[str] = []
    blocks: list[tuple[int, int, dict]] = []
    caption_incomplete = False
    for page_number, page in enumerate(pdf.pages, start=1):
        page_text = page.extract_text() or ""
        if page_text.strip():
            _append(pieces, blocks, page_text, {"kind": "page", "page": page_number})
            continue
        bitmap = rendered[page_number - 1].render(scale=1.6)
        image = bitmap.to_pil().convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=78, optimize=True)
        caption, page_failed = describe(page_number, buffer.getvalue(), "image/jpeg")
        caption_incomplete = caption_incomplete or page_failed
        page_content = f"页面图像描述：{caption}" if caption else ""
        _append(pieces, blocks, page_content, {"kind": "page", "page": page_number, "source": "vision"})
    body = "".join(pieces)[:1_000_000]
    if caption_incomplete:
        status = "partial" if body else "needs_vision"
    else:
        status = "ready" if body else "empty"
    return body, blocks, status


def claim_job(extensions: set[str] | None = None) -> uuid.UUID | None:
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as db:
        reclaim_after = func.now() - text("interval '10 minutes'")
        statement = select(FileIngestJob).join(
            NoteFileVersion, FileIngestJob.file_version_id == NoteFileVersion.id,
        ).where(or_(
            (FileIngestJob.status == "pending") & (FileIngestJob.available_at <= func.now()),
            (FileIngestJob.status == "processing") & (FileIngestJob.updated_at < reclaim_after),
        ))
        if extensions:
            statement = statement.where(NoteFileVersion.extension.in_(extensions))
        job = db.scalar(statement.order_by(FileIngestJob.created_at).with_for_update(skip_locked=True).limit(1))
        if job is None:
            return None
        job.status = "processing"
        job.updated_at = now
        log.info(
            "file_ingest_claimed job=%s queue_wait_seconds=%.3f attempts=%s",
            job.id, max(0.0, (now - job.created_at).total_seconds()), job.attempts,
        )
        return job.id


def process_job(job_id: uuid.UUID) -> None:
    from app.knowledge.m3 import _file_bytes
    from app.knowledge.notes import queue_index

    started_at = time.monotonic()
    with SessionLocal() as db:
        job = db.get(FileIngestJob, job_id)
        if job is None or job.status != "processing":
            log.info("file_ingest_skipped request_id=%s reason=not_claimed", job_id)
            return
        note = db.scalar(select(Note).where(Note.id == job.note_id, Note.user_id == job.user_id))
        row = db.get(NoteFileVersion, job.file_version_id)
        latest = db.scalar(select(NoteFileVersion).where(
            NoteFileVersion.note_id == job.note_id,
            NoteFileVersion.user_id == job.user_id,
        ).order_by(NoteFileVersion.version.desc()).limit(1))
        if note is None or note.deleted_at is not None or row is None or latest is None or latest.id != row.id:
            job.status = "stale"
            job.updated_at = datetime.now(timezone.utc)
            note_id_value = job.note_id
            db.commit()
            log.info("file_ingest_skipped request_id=%s reason=newer_version_exists note=%s", job_id, note_id_value)
            return
        if row.extraction_status == "preserved":
            job.status = "stale"
            job.updated_at = datetime.now(timezone.utc)
            note_id_value = job.note_id
            db.commit()
            log.info("file_ingest_skipped request_id=%s reason=preserved note=%s", job_id, note_id_value)
            return
        try:
            content = _file_bytes(row)
        except HTTPException:
            raise
        user_id = job.user_id
        extension = row.extension
        note_id_value = job.note_id
        vision_results = dict(job.vision_results or {})
        log.info(
            "file_ingest_extract_started request_id=%s note=%s extension=%s bytes=%s attempts=%s",
            job_id, note_id_value, extension, len(content), job.attempts,
        )

    def save_vision_result(page_number: int, caption: str, status: str) -> None:
        with SessionLocal.begin() as db:
            job = db.scalar(select(FileIngestJob).where(
                FileIngestJob.id == job_id,
                FileIngestJob.status == "processing",
            ).with_for_update())
            if job is None:
                return
            results = dict(job.vision_results or {})
            results[str(page_number)] = {"caption": caption, "status": status}
            job.vision_results = results
            job.updated_at = datetime.now(timezone.utc)

    with SessionLocal() as recognition_db:
        body, blocks, extraction_status = extract_file(
            extension, content, recognition_db, user_id,
            vision_results=vision_results,
            save_vision_result=save_vision_result,
        )

    # Apply the same storage-safety check to every format, including parser and
    # OCR output, before fingerprinting or assigning text to PostgreSQL fields.
    # The sanitizer is length-preserving, so block offsets remain aligned.
    body = sanitize_extracted_text(body)

    with SessionLocal.begin() as db:
        job = db.scalar(select(FileIngestJob).where(FileIngestJob.id == job_id).with_for_update())
        if job is None or job.status != "processing":
            return
        note = db.scalar(select(Note).where(Note.id == job.note_id, Note.user_id == job.user_id).with_for_update())
        row = db.get(NoteFileVersion, job.file_version_id)
        latest = db.scalar(select(NoteFileVersion).where(
            NoteFileVersion.note_id == job.note_id,
            NoteFileVersion.user_id == job.user_id,
        ).order_by(NoteFileVersion.version.desc()).limit(1))
        if note is None or note.deleted_at is not None or row is None or latest is None or latest.id != row.id:
            job.status = "stale"
            job.updated_at = datetime.now(timezone.utc)
            return

        fingerprint_input = json.dumps({"parser": 3, "extension": extension, "body": body, "blocks": blocks}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(fingerprint_input.encode()).hexdigest()
        previous = db.scalar(select(NoteFileVersion).where(
            NoteFileVersion.note_id == note.id,
            NoteFileVersion.user_id == note.user_id,
            NoteFileVersion.version < row.version,
            NoteFileVersion.extraction_fingerprint.is_not(None),
        ).order_by(NoteFileVersion.version.desc()).limit(1))
        content_changed = (
            (row.extraction_fingerprint != fingerprint and (previous is None or previous.extraction_fingerprint != fingerprint))
            or note.body_md != body
        )
        row.extraction_fingerprint = fingerprint
        row.extraction_status = extraction_status
        row.extraction_error = None
        if content_changed:
            note.body_md = body
            note.content_version += 1
            db.add_all(
                NoteTextBlock(
                    user_id=note.user_id,
                    note_id=note.id,
                    content_version=note.content_version,
                    ordinal=ordinal,
                    start_offset=start,
                    end_offset=end,
                    locator=locator,
                )
                for ordinal, (start, end, locator) in enumerate(blocks)
            )
            queue_index(db, note)
            if extension in IMAGE_EXTENSIONS:
                from app.knowledge.markdown_images import invalidate_markdown_references

                invalidate_markdown_references(db, user_id, note.id)
        elif extraction_status in {"empty", "unsupported", "needs_vision"}:
            note.index_status = NoteIndexStatus.READY
        job.status = "done"
        job.last_error = None
        job.updated_at = datetime.now(timezone.utc)
        blocks_count = len(blocks)

    log.info(
        "file_ingest_finished request_id=%s note=%s status=%s content_changed=%s blocks=%s extracted_chars=%s elapsed_seconds=%.3f",
        job_id, note_id_value, extraction_status, content_changed, blocks_count, len(body), time.monotonic() - started_at,
    )


def retry_job(job_id: uuid.UUID, error: str) -> None:
    from app.core.models import Note

    with SessionLocal.begin() as db:
        job = db.scalar(select(FileIngestJob).where(FileIngestJob.id == job_id).with_for_update())
        if job is None or job.status != "processing":
            return
        job.attempts += 1
        job.last_error = error[:500]
        job.updated_at = datetime.now(timezone.utc)
        note = db.scalar(select(Note).where(Note.id == job.note_id, Note.user_id == job.user_id))
        row = db.get(NoteFileVersion, job.file_version_id)
        if job.attempts >= 5:
            job.status = "failed"
            if row:
                row.extraction_status = "error"
                row.extraction_error = "识别失败，可重试处理"
            if note:
                note.index_status = NoteIndexStatus.ERROR
            attempts, note_id_value = job.attempts, job.note_id
            # 达到重试上限是「该文件永久无法识别」的分界点，用 error 级别留下明确结论。
            log.error(
                "file_ingest_abandoned request_id=%s note=%s attempts=%s error=%s",
                job_id, note_id_value, attempts, error[:200],
            )
        else:
            delay = min(900, 10 * (2 ** (job.attempts - 1)))
            job.status = "pending"
            job.available_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            attempts, note_id_value = job.attempts, job.note_id
            log.warning(
                "file_ingest_retry request_id=%s note=%s attempts=%s retry_in_seconds=%s error=%s",
                job_id, note_id_value, attempts, delay, error[:200],
            )
