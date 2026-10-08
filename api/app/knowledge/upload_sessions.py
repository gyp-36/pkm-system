"""Authenticated, resumable S3 multipart upload sessions."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.auth.auth import Db, UserId
from app.core import object_storage
from app.core.enums import AuditAction, AuditEntityType, NoteIndexStatus
from app.core.lifecycle import record_event, record_revision
from app.core.models import FileIngestJob, FileUploadSession, Note, NoteChunk, NoteFileVersion
from app.core.ownership import owned_session
from app.contracts.upload_sessions import (PartsReceiptOut, PartUrlOut, UploadActionResultOut, UploadSessionListOut, UploadSessionOut)
from app.knowledge.notes import safe_filename, validate_categories
from app.knowledge.file_types import ALLOWED_EXTENSIONS, MIME_BY_EXT

router = APIRouter(prefix="/v1/file-uploads", tags=["file-uploads"])
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
PART_SIZE = 5 * 1024 * 1024
SESSION_TTL = timedelta(hours=24)
class UploadStart(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=MAX_UPLOAD_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    notebook_id: uuid.UUID | None = None
    convert_legacy: bool = False


class PartReceipt(BaseModel):
    etag: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(ge=1, le=PART_SIZE)


class CompleteParts(BaseModel):
    parts: list[int] = Field(min_length=1, max_length=5)


def _fingerprint(body: UploadStart) -> str:
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _part_count(session: FileUploadSession) -> int:
    return math.ceil(session.size_bytes / PART_SIZE)


def _part_size(session: FileUploadSession, part_number: int) -> int:
    start = (part_number - 1) * PART_SIZE
    return min(PART_SIZE, session.size_bytes - start)


def _session_json(session: FileUploadSession, *, include_url_for: int | None = None) -> dict:
    return {
        "id": str(session.id),
        "status": session.status,
        "filename": session.filename,
        "size_bytes": session.size_bytes,
        "sha256": session.expected_sha256,
        "part_size": PART_SIZE,
        "part_count": _part_count(session),
        "uploaded_parts": session.uploaded_parts,
        "expires_at": session.expires_at.isoformat(),
        "created_at": session.created_at.isoformat(),
        "note_id": str(session.note_id) if session.note_id else None,
        "duplicate_note_id": str(session.duplicate_note_id) if session.duplicate_note_id else None,
        "last_error": session.last_error,
        "part_url": object_storage.part_url(session.object_key, session.multipart_id, include_url_for) if include_url_for else None,
    }


@router.post("/sessions", status_code=201, response_model=UploadSessionOut)
def create_session(
    body: UploadStart,
    db: Db,
    user_id: UserId,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=80),
) -> dict:
    filename = Path(body.filename).name
    extension = Path(filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="支持 md、docx、xlsx、pdf、png、jpg、jpeg、gif、bmp、webp、tif、tiff、ico、doc、xls")
    if extension in {"doc", "xls"} and not body.convert_legacy:
        raise HTTPException(status_code=409, detail="上传旧版 Office 文件前需确认转换为 DOCX/XLSX，原件会保留供下载")
    if body.notebook_id:
        validate_categories(db, user_id, body.notebook_id, [])
    fingerprint = _fingerprint(body.model_copy(update={"filename": filename}))
    existing = db.scalar(select(FileUploadSession).where(
        FileUploadSession.user_id == user_id,
        FileUploadSession.idempotency_key == idempotency_key,
    ))
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="幂等键已用于不同文件参数")
        return _session_json(existing)

    from app.knowledge.m3 import find_duplicate_file, duplicate_file_error
    duplicate = find_duplicate_file(db, user_id, body.sha256)
    if duplicate:
        raise duplicate_file_error(*duplicate)

    key = str(uuid.uuid4())
    upload_id = object_storage.create_multipart(key, MIME_BY_EXT[extension])
    session = FileUploadSession(
        user_id=user_id,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        filename=safe_filename(filename, "file")[:255],
        extension=extension,
        media_type=MIME_BY_EXT[extension],
        size_bytes=body.size_bytes,
        expected_sha256=body.sha256,
        convert_legacy=body.convert_legacy,
        object_key=key,
        multipart_id=upload_id,
        notebook_id=body.notebook_id,
        status="uploading",
        expires_at=datetime.now(timezone.utc) + SESSION_TTL,
    )
    db.add(session)
    db.flush()
    record_event(db, user_id, AuditAction.CREATE, AuditEntityType.UPLOAD_SESSION, session.id,
                 details={"changed": ["filename", "size_bytes", "sha256"], "filename": session.filename})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        object_storage.abort_multipart(key, upload_id)
        existing = db.scalar(select(FileUploadSession).where(
            FileUploadSession.user_id == user_id,
            FileUploadSession.idempotency_key == idempotency_key,
        ))
        if existing and existing.request_fingerprint == fingerprint:
            return _session_json(existing)
        raise HTTPException(status_code=409, detail="上传会话创建冲突，请重试") from None
    db.refresh(session)
    return _session_json(session)


@router.get("/sessions", response_model=UploadSessionListOut)
def list_resumable_sessions(db: Db, user_id: UserId) -> dict:
    rows = db.scalars(select(FileUploadSession).where(
        FileUploadSession.user_id == user_id,
        or_(
            FileUploadSession.status == "completed",
            and_(
                FileUploadSession.status.in_(["uploading", "completing", "failed"]),
                FileUploadSession.expires_at > datetime.now(timezone.utc),
            ),
        ),
    ).order_by(FileUploadSession.created_at.desc()).limit(100)).all()
    return {"items": [_session_json(row) for row in rows]}


@router.post("/sessions/{upload_id}/retry-ingest", response_model=UploadActionResultOut)
@router.post("/sessions/{upload_id}/retry", response_model=UploadActionResultOut)
def retry_ingest(upload_id: uuid.UUID, db: Db, user_id: UserId) -> dict:
    session = owned_session(db, user_id, upload_id, lock=True)
    if session.status != "completed" or not session.note_id:
        raise HTTPException(status_code=409, detail="文件尚未完成保存，不能重试识别")
    note = db.scalar(select(Note).where(Note.id == session.note_id, Note.user_id == user_id))
    row = db.scalar(select(NoteFileVersion).where(
        NoteFileVersion.note_id == session.note_id,
        NoteFileVersion.user_id == user_id,
        NoteFileVersion.storage_key == session.object_key,
    ).limit(1))
    if row is not None and session.convert_legacy:
        row = db.scalar(select(NoteFileVersion).where(
            NoteFileVersion.note_id == session.note_id,
            NoteFileVersion.user_id == user_id,
            NoteFileVersion.storage_key == f"{session.object_key}.converted",
        ).limit(1)) or row
    if note is None or row is None:
        raise HTTPException(status_code=404, detail="文件版本不存在")
    latest = db.scalar(select(NoteFileVersion).where(
        NoteFileVersion.note_id == note.id,
        NoteFileVersion.user_id == user_id,
    ).order_by(NoteFileVersion.version.desc()).limit(1))
    if latest is None or latest.id != row.id:
        raise HTTPException(status_code=409, detail="该上传记录已被后续文件版本替换，请在当前版本上重试")
    if row.extraction_status not in {"error", "needs_vision", "partial"}:
        if row.extraction_status not in {"ready", "empty", "unsupported"} or note.index_status != NoteIndexStatus.ERROR:
            raise HTTPException(status_code=409, detail="当前文件没有可重试的识别或索引任务")
        from app.knowledge.notes import queue_index
        queue_index(db, note)
        record_event(db, user_id, AuditAction.UPDATE, AuditEntityType.UPLOAD_SESSION, session.id,
                     details={"retry": "index", "note_id": str(note.id)})
        db.commit()
        db.refresh(note)
        from app.knowledge.m3 import note_payload
        return {"status": "pending", "note": note_payload(db, note)}
    job = db.scalar(select(FileIngestJob).where(FileIngestJob.file_version_id == row.id).with_for_update())
    if job is None:
        job = FileIngestJob(user_id=user_id, note_id=note.id, file_version_id=row.id, status="pending")
        db.add(job)
    else:
        job.status = "pending"
        job.attempts = 0
        job.last_error = None
        job.available_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
    row.extraction_status = "pending"
    row.extraction_error = None
    record_event(db, user_id, AuditAction.UPDATE, AuditEntityType.UPLOAD_SESSION, session.id,
                 details={"retry": "ingest", "note_id": str(note.id)})
    db.commit()
    from app.knowledge.m3 import note_payload
    db.refresh(note)
    return {"status": "pending", "note": note_payload(db, note)}


@router.get("/sessions/{upload_id}", response_model=UploadSessionOut)
def get_session(upload_id: uuid.UUID, db: Db, user_id: UserId) -> dict:
    session = owned_session(db, user_id, upload_id)
    result = _session_json(session)
    if session.note_id:
        from app.knowledge.m3 import note_payload
        note = db.scalar(select(Note).where(Note.id == session.note_id, Note.user_id == user_id))
        if note:
            payload = note_payload(db, note)
            uploaded_version = db.scalar(select(NoteFileVersion).where(
                NoteFileVersion.note_id == note.id,
                NoteFileVersion.user_id == user_id,
                NoteFileVersion.storage_key == session.object_key,
            ).limit(1))
            if uploaded_version and session.convert_legacy:
                converted_version = db.scalar(select(NoteFileVersion).where(
                    NoteFileVersion.note_id == note.id,
                    NoteFileVersion.user_id == user_id,
                    NoteFileVersion.storage_key == f"{session.object_key}.converted",
                ).limit(1))
                uploaded_version = converted_version or uploaded_version
            latest_version = db.scalar(select(NoteFileVersion).where(
                NoteFileVersion.note_id == note.id,
                NoteFileVersion.user_id == user_id,
            ).order_by(NoteFileVersion.version.desc()).limit(1))
            if uploaded_version:
                from app.knowledge.m3 import file_meta
                payload["file"] = file_meta(uploaded_version)
                payload["file"]["is_current_version"] = uploaded_version.id == latest_version.id if latest_version else False
                if payload["file"]["is_current_version"]:
                    payload["indexed_chunks"] = db.scalar(select(func.count()).select_from(NoteChunk).where(
                        NoteChunk.note_id == note.id,
                        NoteChunk.user_id == user_id,
                        NoteChunk.note_version == note.content_version,
                    )) or 0
                else:
                    payload["index_status"] = "superseded"
                    payload["indexed_chunks"] = 0
            result["note"] = payload
        else:
            result["note"] = None
    if session.duplicate_note_id:
        note = db.scalar(select(Note).where(Note.id == session.duplicate_note_id, Note.user_id == user_id))
        result["duplicate"] = {"id": str(note.id), "title": note.title} if note else None
    return result


@router.post("/sessions/{upload_id}/parts/{part_number}/url", response_model=PartUrlOut)
def get_part_url(upload_id: uuid.UUID, part_number: int, db: Db, user_id: UserId) -> dict:
    session = owned_session(db, user_id, upload_id)
    if session.status != "uploading" or not 1 <= part_number <= _part_count(session):
        raise HTTPException(status_code=409, detail="上传会话状态或分块序号无效")
    return {"url": object_storage.part_url(session.object_key, session.multipart_id, part_number), "size_bytes": _part_size(session, part_number), "expires_in": 900}


@router.put("/sessions/{upload_id}/parts/{part_number}/receipt", response_model=PartsReceiptOut)
def confirm_part(upload_id: uuid.UUID, part_number: int, body: PartReceipt, db: Db, user_id: UserId) -> dict:
    session = owned_session(db, user_id, upload_id, lock=True)
    if session.status != "uploading" or not 1 <= part_number <= _part_count(session):
        raise HTTPException(status_code=409, detail="上传会话状态或分块序号无效")
    if body.size_bytes != _part_size(session, part_number):
        raise HTTPException(status_code=422, detail="分块大小不匹配")
    parts = {item["part_number"]: item for item in session.uploaded_parts}
    parts[part_number] = {"part_number": part_number, "etag": body.etag, "size_bytes": body.size_bytes}
    session.uploaded_parts = [parts[number] for number in sorted(parts)]
    session.updated_at = datetime.now(timezone.utc)
    record_event(db, user_id, AuditAction.UPDATE, AuditEntityType.UPLOAD_SESSION, session.id,
                 details={"changed": ["uploaded_parts"], "part_number": part_number})
    db.commit()
    return {"uploaded_parts": session.uploaded_parts}


def _lock_user_hash(db: Db, user_id: UserId, digest: str) -> None:
    lock_digest = hashlib.sha256(f"{user_id}:{digest}".encode()).digest()
    lock_id = int.from_bytes(lock_digest[:8], "big", signed=True)
    db.execute(select(func.pg_advisory_xact_lock(lock_id)))


def _create_note_for_upload(db: Db, session: FileUploadSession, user_id: UserId, *, converted: tuple[str, bytes] | None = None) -> Note:
    from app.knowledge.m3 import _check_file
    note = Note(
        user_id=user_id,
        notebook_id=session.notebook_id,
        title=Path(session.filename).stem[:240] or "未命名文件",
        body_md="",
        version=1,
        content_version=1,
        content_kind=session.extension,
    )
    db.add(note)
    db.flush()
    original = NoteFileVersion(
        user_id=user_id,
        note_id=note.id,
        version=1,
        filename=session.filename,
        extension=session.extension,
        media_type=session.media_type,
        storage_key=session.object_key,
        size_bytes=session.size_bytes,
        sha256=session.expected_sha256,
        storage_backend="s3",
        extraction_status="preserved" if converted else "pending",
    )
    db.add(original)
    latest = original
    if converted:
        converted_ext, content = converted
        converted_name = f"{Path(session.filename).stem}.{converted_ext}"
        # 如果笔记事务回滚，该值在重试完成操作时仍保持不变。
        converted_key = f"{session.object_key}.converted"
        media_type = MIME_BY_EXT[converted_ext]
        _check_file(converted_ext, content)
        object_storage.put(converted_key, content, media_type)
        latest = NoteFileVersion(
            user_id=user_id,
            note_id=note.id,
            version=2,
            filename=safe_filename(converted_name, "file")[:255],
            extension=converted_ext,
            media_type=media_type,
            storage_key=converted_key,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            storage_backend="s3",
            extraction_status="pending",
        )
        db.add(latest)
        note.content_kind = converted_ext
    db.flush()
    db.add(FileIngestJob(user_id=user_id, note_id=note.id, file_version_id=latest.id, status="pending"))
    record_revision(db, note, [])
    record_event(db, user_id, AuditAction.CREATE, AuditEntityType.NOTE, note.id, entity_version=note.version, details={"fields": ["content_kind"]})
    return note


@router.post("/sessions/{upload_id}/complete", response_model=UploadActionResultOut)
def complete_session(upload_id: uuid.UUID, body: CompleteParts, db: Db, user_id: UserId) -> dict:
    session = owned_session(db, user_id, upload_id, lock=True)
    if session.status == "completed":
        from app.knowledge.m3 import note_payload
        note = db.scalar(select(Note).where(Note.id == session.note_id, Note.user_id == user_id))
        return {"status": "completed", "note": note_payload(db, note)}
    if session.status == "duplicate":
        note = db.scalar(select(Note).where(Note.id == session.duplicate_note_id, Note.user_id == user_id))
        return {"status": "duplicate", "duplicate": {"id": str(note.id), "title": note.title} if note else None}
    if session.status == "completing" and session.updated_at > datetime.now(timezone.utc) - timedelta(seconds=30):
        return {"status": "completing", "message": "文件正在校验并保存"}
    expected_count = _part_count(session)
    if body.parts != list(range(1, expected_count + 1)):
        raise HTTPException(status_code=422, detail="上传分块不完整或顺序无效")
    stored = {item["part_number"]: item for item in session.uploaded_parts}
    if set(stored) != set(body.parts) or any(stored[number]["size_bytes"] != _part_size(session, number) for number in body.parts):
        raise HTTPException(status_code=409, detail="仍有分块未确认，请先完成上传")
    if session.status not in {"uploading", "completing"}:
        raise HTTPException(status_code=409, detail="上传会话不可完成")
    session.status = "completing"
    session.updated_at = datetime.now(timezone.utc)
    db.commit()

    try:
        try:
            object_storage.complete_multipart(session.object_key, session.multipart_id, [stored[n] for n in body.parts])
        except Exception:
            # 即使 S3 已完成分段上传但响应丢失，重试也是安全的。
            object_storage.head(session.object_key)
        actual_sha, actual_size = object_storage.hash_object(session.object_key)
        if actual_size != session.size_bytes or actual_sha != session.expected_sha256:
            object_storage.delete(session.object_key)
            session.status = "failed"
            session.last_error = "文件校验失败"
            record_event(db, user_id, AuditAction.UPDATE, AuditEntityType.UPLOAD_SESSION, session.id,
                         details={"changed": ["status"], "status": "failed", "reason": "checksum_mismatch"})
            db.commit()
            raise HTTPException(status_code=422, detail="文件校验失败，请重新选择文件")

        from app.knowledge.m3 import _check_file, find_duplicate_file, duplicate_file_error, note_payload, convert_legacy_office
        content = object_storage.get(session.object_key)
        try:
            _check_file(session.extension, content)
        except HTTPException:
            object_storage.delete(session.object_key)
            session.status = "failed"
            session.last_error = "文件格式无效或内容已损坏"
            record_event(db, user_id, AuditAction.UPDATE, AuditEntityType.UPLOAD_SESSION, session.id,
                         details={"changed": ["status"], "status": "failed", "reason": "invalid_format"})
            db.commit()
            raise
        _lock_user_hash(db, user_id, actual_sha)
        duplicate = find_duplicate_file(db, user_id, actual_sha)
        if duplicate:
            session.status = "duplicate"
            session.duplicate_note_id = duplicate[0].id
            record_event(db, user_id, AuditAction.UPDATE, AuditEntityType.UPLOAD_SESSION, session.id,
                         details={"changed": ["status"], "status": "duplicate", "note_id": str(duplicate[0].id)})
            db.commit()
            object_storage.delete(session.object_key)
            return {"status": "duplicate", "duplicate": {"id": str(duplicate[0].id), "title": duplicate[0].title, "filename": duplicate[1].filename}}

        converted = None
        if session.extension in {"doc", "xls"}:
            converted = convert_legacy_office(session.filename, session.extension, session.object_key, session.media_type)
        note = _create_note_for_upload(db, session, user_id, converted=converted)
        session.status = "completed"
        session.note_id = note.id
        session.last_error = None
        record_event(db, user_id, AuditAction.UPDATE, AuditEntityType.UPLOAD_SESSION, session.id,
                     details={"changed": ["status"], "status": "completed", "note_id": str(note.id),
                              "filename": session.filename, "size_bytes": session.size_bytes})
        db.commit()
        db.refresh(note)
        return {"status": "completed", "note": note_payload(db, note)}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        session = db.get(FileUploadSession, upload_id)
        if session and session.user_id == user_id:
            session.status = "uploading" if session.expires_at > datetime.now(timezone.utc) else "failed"
            session.last_error = type(exc).__name__
            record_event(db, user_id, AuditAction.UPDATE, AuditEntityType.UPLOAD_SESSION, session.id,
                         details={"changed": ["status"], "status": session.status,
                                  "reason": "merge_failed", "error": type(exc).__name__})
            db.commit()
        raise HTTPException(status_code=502, detail="文件合并或保存失败，可重试完成") from None


@router.delete("/sessions/{upload_id}", status_code=204)
def cancel_session(upload_id: uuid.UUID, db: Db, user_id: UserId) -> None:
    session = owned_session(db, user_id, upload_id, lock=True)
    if session.status in {"completed", "duplicate"}:
        raise HTTPException(status_code=409, detail="已完成的上传不能取消")
    if session.status == "completing":
        raise HTTPException(status_code=409, detail="文件正在合并校验，暂时不能取消")
    if session.status not in {"uploading", "failed"}:
        raise HTTPException(status_code=409, detail="当前上传状态不能取消")
    object_storage.abort_multipart(session.object_key, session.multipart_id)
    session.status = "cancelled"
    session.updated_at = datetime.now(timezone.utc)
    record_event(db, user_id, AuditAction.DELETE, AuditEntityType.UPLOAD_SESSION, session.id,
                 details={"status": "cancelled", "filename": session.filename})
    db.commit()


def cleanup_expired_sessions(db: Db) -> int:
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(FileUploadSession).where(
        FileUploadSession.status.in_(["uploading", "completing", "failed"]),
        FileUploadSession.expires_at <= now,
    ).with_for_update(skip_locked=True).limit(100)).all()
    for session in rows:
        try:
            object_storage.abort_multipart(session.object_key, session.multipart_id)
        finally:
            session.status = "expired"
            session.updated_at = now
    db.commit()
    return len(rows)
