"""回收站 API 与到期笔记清理。"""

import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.auth.auth import Db, UserId
from app.core.db import SessionLocal
from app.core.enums import AuditAction, AuditEntityType
from app.core.lifecycle import record_event
from app.core.models import (
    AssistantMessage,
    DigestRun,
    FileIngestJob,
    FileUploadSession,
    IndexJob,
    MarkdownImageReference,
    Note,
    NoteChunk,
    NoteFileVersion,
    NoteReminder,
    NoteRevision,
    NoteTag,
    NoteTextBlock,
    Notebook,
    Tag,
)
from app.core import object_storage
from app.knowledge.file_types import IMAGE_EXTENSIONS


router = APIRouter(prefix="/v1/notes/archive", tags=["archive"])
RETENTION_DAYS = 30
RETENTION = timedelta(days=RETENTION_DAYS)
FILE_ROOT = Path(os.getenv("NOTE_FILE_ROOT", "/data/note-files"))


class PurgeRequest(BaseModel):
    note_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


def _file_path(storage_key: str) -> Path:
    if not re.fullmatch(r"[0-9a-f-]{36}", storage_key):
        raise ValueError("文件存储记录无效")
    return FILE_ROOT / storage_key[:2] / storage_key


def _delete_file(row: NoteFileVersion) -> None:
    if row.storage_backend == "s3":
        object_storage.delete(row.storage_key)
    elif row.storage_backend == "filesystem":
        _file_path(row.storage_key).unlink(missing_ok=True)
    else:
        raise ValueError("不支持的文件存储类型")


def _archive_json(db: Session, note: Note) -> dict:
    from app.knowledge.notes import note_json

    deleted_at = note.deleted_at or datetime.now(timezone.utc)
    purge_at = deleted_at + RETENTION
    remaining = max(0, int((purge_at - datetime.now(timezone.utc)).total_seconds() + 86399) // 86400)
    return {
        **note_json(db, note, include_body=False),
        "deleted_at": deleted_at.isoformat(),
        "purge_at": purge_at.isoformat(),
        "days_remaining": remaining,
    }


@router.get("")
def list_archive(
    db: Db,
    user_id: UserId,
    limit: int = 100,
    cursor: uuid.UUID | None = None,
) -> dict:
    limit = max(1, min(limit, 100))
    query = select(Note).where(Note.user_id == user_id, Note.deleted_at.is_not(None))
    if cursor is not None:
        cursor_note = db.scalar(select(Note).where(
            Note.id == cursor,
            Note.user_id == user_id,
            Note.deleted_at.is_not(None),
        ))
        if cursor_note is None:
            raise HTTPException(status_code=400, detail="无效的归档列表游标")
        query = query.where(or_(
            Note.deleted_at < cursor_note.deleted_at,
            (Note.deleted_at == cursor_note.deleted_at) & (Note.id < cursor),
        ))
    rows = db.scalars(query.order_by(Note.deleted_at.desc(), Note.id.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    return {
        "items": [_archive_json(db, note) for note in page],
        "next_cursor": str(page[-1].id) if len(rows) > limit else None,
    }


@router.post("/{note_id}/restore")
def restore_archived_note(note_id: uuid.UUID, db: Db, user_id: UserId) -> dict:
    note = db.scalar(select(Note).where(
        Note.id == note_id,
        Note.user_id == user_id,
        Note.deleted_at.is_not(None),
    ).with_for_update())
    if note is None:
        raise HTTPException(status_code=404, detail="归档笔记不存在")

    if note.notebook_id is not None and db.scalar(select(Notebook.id).where(
        Notebook.id == note.notebook_id,
        Notebook.user_id == user_id,
        Notebook.deleted_at.is_(None),
    )) is None:
        note.notebook_id = None

    db.execute(delete(NoteTag).where(
        NoteTag.user_id == user_id,
        NoteTag.note_id == note.id,
        NoteTag.tag_id.not_in(select(Tag.id).where(Tag.user_id == user_id, Tag.deleted_at.is_(None))),
    ))
    note.deleted_at = None
    note.updated_at = datetime.now(timezone.utc)
    if note.content_kind in IMAGE_EXTENSIONS:
        from app.knowledge.markdown_images import invalidate_markdown_references

        invalidate_markdown_references(db, user_id, note.id)
    has_chunks = db.scalar(select(NoteChunk.id).where(
        NoteChunk.note_id == note.id,
        NoteChunk.user_id == user_id,
    ).limit(1))
    has_image_references = db.scalar(select(MarkdownImageReference.markdown_note_id).where(
        MarkdownImageReference.markdown_note_id == note.id,
        MarkdownImageReference.user_id == user_id,
    ).limit(1)) is not None
    if not has_chunks or has_image_references:
        from app.knowledge.notes import queue_index

        note.content_version += 1
        queue_index(db, note)
    record_event(db, user_id, AuditAction.RESTORE, AuditEntityType.NOTE, note.id, entity_version=note.version)
    db.commit()
    return {"id": str(note.id), "title": note.title}


def purge_archived_note(
    db: Session,
    user_id: uuid.UUID,
    note_id: uuid.UUID,
    *,
    expired_before: datetime | None = None,
) -> bool:
    note = db.scalar(select(Note).where(
        Note.id == note_id,
        Note.user_id == user_id,
        Note.deleted_at.is_not(None),
    ).with_for_update())
    if note is None or (expired_before is not None and note.deleted_at > expired_before):
        return False

    if note.content_kind in IMAGE_EXTENSIONS:
        from app.knowledge.markdown_images import invalidate_markdown_references

        invalidate_markdown_references(db, user_id, note.id)

    versions = db.scalars(select(NoteFileVersion).where(
        NoteFileVersion.note_id == note.id,
        NoteFileVersion.user_id == user_id,
    )).all()
    try:
        for version in versions:
            _delete_file(version)
    except Exception as exc:
        db.rollback()
        raise RuntimeError("文件存储清理失败") from exc

    db.execute(delete(FileIngestJob).where(FileIngestJob.note_id == note.id, FileIngestJob.user_id == user_id))
    db.execute(delete(IndexJob).where(IndexJob.note_id == note.id, IndexJob.user_id == user_id))
    db.execute(delete(NoteChunk).where(NoteChunk.note_id == note.id, NoteChunk.user_id == user_id))
    db.execute(delete(NoteTextBlock).where(NoteTextBlock.note_id == note.id, NoteTextBlock.user_id == user_id))
    db.execute(delete(NoteTag).where(NoteTag.note_id == note.id, NoteTag.user_id == user_id))
    db.execute(delete(MarkdownImageReference).where(
        MarkdownImageReference.markdown_note_id == note.id,
        MarkdownImageReference.user_id == user_id,
    ))
    db.execute(delete(NoteRevision).where(NoteRevision.note_id == note.id, NoteRevision.user_id == user_id))
    db.execute(delete(FileUploadSession).where(
        FileUploadSession.user_id == user_id,
        or_(FileUploadSession.note_id == note.id, FileUploadSession.duplicate_note_id == note.id),
    ))
    db.execute(delete(AssistantMessage).where(
        AssistantMessage.user_id == user_id,
        or_(
            AssistantMessage.content["citations"].contains([{"note_id": str(note.id)}]),
            AssistantMessage.content["items"].contains([{"note_id": str(note.id)}]),
        ),
    ))
    db.execute(delete(NoteFileVersion).where(NoteFileVersion.note_id == note.id, NoteFileVersion.user_id == user_id))
    # 提醒依附于笔记的生命周期：笔记一旦永久消失，提醒文本（例如"补充第三节"）已失去指代对象。
    # 这里删除而不是把 note_id 置空——置空会让它变成一条独立提醒重新出现在提醒列表里，
    # 而列表接口本就按"笔记可用"过滤（见 app.knowledge.reminders），置空等于把用户没做过的改动
    # 强加给他。软删除阶段该提醒被隐藏但保留，是为了让"恢复笔记"能把提醒一起带回来；
    # 走到永久删除这一步，这个可逆性已经不存在了。
    reminders_deleted = db.execute(delete(NoteReminder).where(
        NoteReminder.note_id == note.id,
        NoteReminder.user_id == user_id,
    )).rowcount or 0
    # 周报运行记录是排期账本，必须比它产出的笔记活得久：删掉记录会让同一个 slot 被重新排期
    # （唯一约束只保证 `(user_id, kind, slot_key)` 不重复），因此只解除指向笔记的引用，
    # 保留 status / period / source_refs，让"这份报告生成过、但笔记已被永久删除"仍可追溯。
    # 清空后 /v1/digests 返回的 note_id / note_active / note_archived 与悬空引用时完全一致，
    # 前端无感知；`updated_at` 保持不动，它是报告自己的时间戳，不该被一次清理改写。
    digest_runs_detached = db.execute(update(DigestRun).where(
        DigestRun.note_id == note.id,
        DigestRun.user_id == user_id,
    ).values(note_id=None)).rowcount or 0
    # 审计事件不参与级联清理：永久删除是最不可逆的动作，恰恰最需要留痕，
    # 历史审计行必须比笔记本身活得更久。entity_id 指向已不存在的笔记是允许的——
    # 审计的职责就是证明「它曾经存在过，且被谁在何时删掉了」。
    # 唯一的例外是账号注销：那次清除属于个人数据删除，由 app.ops.maintenance 统一处理。
    record_event(db, user_id, AuditAction.DELETE, AuditEntityType.NOTE, note.id,
                 entity_version=note.version,
                 details={"purged": True, "reminders_deleted": reminders_deleted,
                          "digest_runs_detached": digest_runs_detached})
    db.delete(note)
    db.commit()
    return True


@router.delete("/{note_id}", status_code=204)
def purge_one_archived_note(note_id: uuid.UUID, db: Db, user_id: UserId) -> None:
    try:
        if not purge_archived_note(db, user_id, note_id):
            raise HTTPException(status_code=404, detail="归档笔记不存在")
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.post("/purge")
def purge_selected_archived_notes(body: PurgeRequest, db: Db, user_id: UserId) -> dict:
    purged: list[str] = []
    failed: list[dict[str, str]] = []
    for note_id in dict.fromkeys(body.note_ids):
        try:
            if purge_archived_note(db, user_id, note_id):
                purged.append(str(note_id))
            else:
                failed.append({"id": str(note_id), "error": "归档笔记不存在"})
        except Exception as exc:
            db.rollback()
            logging.exception("归档笔记清除失败：%s", note_id)
            failed.append({"id": str(note_id), "error": str(exc) if isinstance(exc, RuntimeError) else "清除失败，请重试"})
    return {"purged": purged, "failed": failed}


def purge_expired_archive(batch_size: int = 100) -> int:
    cutoff = datetime.now(timezone.utc) - RETENTION
    purged = 0
    last_deleted_at: datetime | None = None
    last_note_id: uuid.UUID | None = None

    # 使用键集分页扫描所有到期记录，避免将全部笔记 ID 加载到内存中。
    # 快照中包含 user_id，使每条记录都在独立事务中处理，单条失败不会阻塞批次中的其他记录。
    while True:
        query = select(Note.id, Note.user_id, Note.deleted_at).where(
            Note.deleted_at.is_not(None),
            Note.deleted_at <= cutoff,
        )
        if last_deleted_at is not None and last_note_id is not None:
            query = query.where(or_(
                Note.deleted_at > last_deleted_at,
                (Note.deleted_at == last_deleted_at) & (Note.id > last_note_id),
            ))
        with SessionLocal() as db:
            rows = db.execute(
                query.order_by(Note.deleted_at, Note.id).limit(max(1, batch_size))
            ).all()
        if not rows:
            break

        for note_id, user_id, deleted_at in rows:
            last_deleted_at, last_note_id = deleted_at, note_id
            with SessionLocal() as db:
                try:
                    purged += int(purge_archived_note(
                        db, user_id, note_id, expired_before=cutoff
                    ))
                except Exception:
                    db.rollback()
                    logging.exception("到期归档清除失败：%s", note_id)
    return purged
