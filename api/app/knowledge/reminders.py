"""Persistent account-owned reminders, optionally linked to saved notes."""

import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, or_, select

from app.auth.auth import Db, UserId
from app.core.enums import AuditAction, AuditEntityType
from app.core.lifecycle import record_event
from app.core.models import DigestRun, Note, NoteReminder
from app.knowledge.archive import _archive_json
from app.knowledge.notes import note_json, owned_note


router = APIRouter(prefix="/v1/reminders", tags=["reminders"])
note_router = APIRouter(prefix="/v1/notes", tags=["reminders"])
workbench_router = APIRouter(prefix="/v1/workbench", tags=["workbench"])


class ReminderCreate(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    due_at: datetime
    note_id: uuid.UUID | None = None

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("提醒内容不能为空")
        return value

    @field_validator("due_at")
    @classmethod
    def aware_date(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("提醒时间必须带时区")
        return value


class ReminderUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=200)
    due_at: datetime | None = None
    status: Literal["open", "done"] | None = None

    @field_validator("due_at")
    @classmethod
    def aware_date(cls, value: datetime | None) -> datetime | None:
        return ReminderCreate.aware_date(value) if value is not None else None


def reminder_json(row: NoteReminder, note: Note | None) -> dict:
    return {
        "id": str(row.id), "note_id": str(note.id) if note else None,
        "note_title": note.title if note else None,
        "text": row.text, "due_at": row.due_at.isoformat(), "status": row.status,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    }


def owned_reminder(db: Db, user_id: uuid.UUID, reminder_id: uuid.UUID, *, lock: bool = False) -> NoteReminder:
    query = select(NoteReminder).where(NoteReminder.id == reminder_id, NoteReminder.user_id == user_id, NoteReminder.status != "cancelled")
    if lock:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise HTTPException(status_code=404, detail="提醒不存在")
    return row


@note_router.post("/{note_id}/reminders", status_code=201)
def create_reminder(note_id: uuid.UUID, body: ReminderCreate, db: Db, user_id: UserId) -> dict:
    if body.note_id is not None and body.note_id != note_id:
        raise HTTPException(status_code=422, detail="笔记 ID 与路径不一致")
    note = owned_note(db, note_id, user_id)
    row = NoteReminder(user_id=user_id, note_id=note.id, text=body.text, due_at=body.due_at.astimezone(timezone.utc))
    db.add(row)
    db.flush()
    record_event(db, user_id, AuditAction.CREATE, AuditEntityType.REMINDER, row.id,
                 details={"changed": ["text", "due_at"], "note_id": str(note.id)})
    db.commit()
    db.refresh(row)
    return reminder_json(row, note)


@router.post("", status_code=201)
def create_standalone_or_linked_reminder(body: ReminderCreate, db: Db, user_id: UserId) -> dict:
    note = owned_note(db, body.note_id, user_id) if body.note_id is not None else None
    row = NoteReminder(user_id=user_id, note_id=note.id if note else None,
                       text=body.text, due_at=body.due_at.astimezone(timezone.utc))
    db.add(row)
    db.flush()
    record_event(db, user_id, AuditAction.CREATE, AuditEntityType.REMINDER, row.id,
                 details={"changed": ["text", "due_at"], "note_id": str(note.id) if note else None})
    db.commit()
    db.refresh(row)
    return reminder_json(row, note)


@router.get("")
def list_reminders(
    db: Db, user_id: UserId, status: Literal["open", "done", "all"] = "open",
    note_id: uuid.UUID | None = None, from_at: datetime | None = None, to_at: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=300),
    offset: int = Query(default=0, ge=0),
) -> dict:
    query = select(NoteReminder, Note).outerjoin(
        Note, and_(Note.id == NoteReminder.note_id, Note.user_id == user_id),
    ).where(
        NoteReminder.user_id == user_id, NoteReminder.status != "cancelled",
        or_(NoteReminder.note_id.is_(None), and_(Note.id.is_not(None), Note.deleted_at.is_(None))),
    )
    if status != "all":
        query = query.where(NoteReminder.status == status)
    if note_id is not None:
        query = query.where(NoteReminder.note_id == note_id)
    if from_at is not None:
        query = query.where(NoteReminder.due_at >= from_at)
    if to_at is not None:
        query = query.where(NoteReminder.due_at < to_at)
    rows = db.execute(query.order_by(NoteReminder.due_at, NoteReminder.id).offset(offset).limit(limit + 1)).all()
    return {
        "items": [reminder_json(reminder, note) for reminder, note in rows[:limit]],
        "next_offset": offset + limit if len(rows) > limit else None,
    }


@router.patch("/{reminder_id}")
def update_reminder(reminder_id: uuid.UUID, body: ReminderUpdate, db: Db, user_id: UserId) -> dict:
    row = owned_reminder(db, user_id, reminder_id, lock=True)
    note = owned_note(db, row.note_id, user_id) if row.note_id is not None else None
    if body.text is not None:
        row.text = body.text.strip()
        if not row.text:
            raise HTTPException(status_code=422, detail="提醒内容不能为空")
    if body.due_at is not None:
        row.due_at = body.due_at.astimezone(timezone.utc)
    if body.status is not None:
        row.status = body.status
        row.completed_at = datetime.now(timezone.utc) if body.status == "done" else None
    row.updated_at = datetime.now(timezone.utc)
    record_event(db, user_id, AuditAction.UPDATE, AuditEntityType.REMINDER, row.id,
                 details={"changed": sorted(body.model_fields_set)})
    db.commit()
    db.refresh(row)
    return reminder_json(row, note)


@router.delete("/{reminder_id}", status_code=204)
def cancel_reminder(reminder_id: uuid.UUID, db: Db, user_id: UserId) -> None:
    row = owned_reminder(db, user_id, reminder_id, lock=True)
    row.status = "cancelled"
    row.updated_at = datetime.now(timezone.utc)
    record_event(db, user_id, AuditAction.DELETE, AuditEntityType.REMINDER, row.id,
                 details={"changed": ["status"]})
    db.commit()


@workbench_router.get("")
def workbench_cards(db: Db, user_id: UserId) -> dict:
    now = datetime.now(timezone.utc)
    reminder_rows = db.execute(
        select(NoteReminder, Note).outerjoin(
            Note, and_(Note.id == NoteReminder.note_id, Note.user_id == user_id),
        ).where(
            NoteReminder.user_id == user_id, NoteReminder.status == "open",
            or_(NoteReminder.note_id.is_(None), and_(Note.id.is_not(None), Note.deleted_at.is_(None))),
        ).order_by(NoteReminder.due_at, NoteReminder.id).limit(5)
    ).all()
    reminders = [reminder_json(reminder, note) for reminder, note in reminder_rows]
    # 保留旧聚合响应，模块预览独立取数，避免到期提醒挤掉周报。
    cards = [{"kind": "reminder", **reminder_json(reminder, note)}
             for reminder, note in reminder_rows if reminder.due_at <= now]
    if len(cards) < 5:
        runs = db.scalars(select(DigestRun).where(
            DigestRun.user_id == user_id, DigestRun.status.in_(["ready", "failed"]),
        ).order_by(DigestRun.scheduled_at.desc(), DigestRun.id.desc()).limit(20)).all()
        for run in runs:
            if run.status == "ready" and (run.note_id is None or db.scalar(select(Note.id).where(
                Note.id == run.note_id, Note.user_id == user_id, Note.deleted_at.is_(None),
            )) is None):
                continue
            cards.append({
                "kind": "digest", "id": str(run.id), "report_kind": run.kind,
                "status": run.status, "note_id": str(run.note_id) if run.note_id else None,
                "scheduled_at": run.scheduled_at.isoformat(), "error": run.error,
            })
            if len(cards) == 5:
                break
    reports = {}
    for kind in ("daily", "weekly"):
        latest = db.execute(select(DigestRun, Note).outerjoin(
            Note, and_(Note.id == DigestRun.note_id, Note.user_id == user_id),
        ).where(
            DigestRun.user_id == user_id, DigestRun.kind == kind,
        ).order_by(DigestRun.scheduled_at.desc(), DigestRun.id.desc()).limit(1)).first()
        reports[kind] = None
        if latest:
            run, note = latest
            excerpt, topics = _digest_preview(note.body_md if note and run.status == "ready" else "")
            reports[kind] = {
                "id": str(run.id), "kind": kind, "status": run.status,
                "note_id": str(note.id) if note else None,
                "title": note.title if note else ("每日知识回顾" if kind == "daily" else "一周知识回顾"),
                "excerpt": excerpt, "topics": topics,
                "note_active": note is not None and note.deleted_at is None,
                "note_archived": note is not None and note.deleted_at is not None,
                "period_start": run.period_start.isoformat(), "period_end": run.period_end.isoformat(),
                "scheduled_at": run.scheduled_at.isoformat(), "updated_at": run.updated_at.isoformat(),
            }
    # 固定保留期下，最早删除的笔记也最早自动清除；直接在全库中排序取三条。
    archived = db.scalars(select(Note).where(
        Note.user_id == user_id, Note.deleted_at.is_not(None),
    ).order_by(Note.deleted_at, Note.id).limit(3)).all()
    recent_note = db.scalar(select(Note).where(
        Note.user_id == user_id, Note.deleted_at.is_(None),
    ).order_by(Note.updated_at.desc(), Note.id.desc()).limit(1))
    return {
        "items": cards,
        "reminders": reminders[:3],
        "latest_daily": reports["daily"],
        "latest_weekly": reports["weekly"],
        "archive": [_archive_json(db, note) for note in archived],
        "recent_note": note_json(db, recent_note, include_body=False) if recent_note else None,
    }


def _digest_preview(body: str) -> tuple[str, list[str]]:
    """Only preview actual prose and optional topic subheadings from the saved report."""
    def plain(text: str) -> str:
        text = re.sub(r"\[S\d+\](?:\([^)]*\))?", "", text)
        text = re.sub(r"!\[[^]]*\]\([^)]*\)", "", text)
        text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"[`*_>#~]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    topics = []
    prose = []
    in_code = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_code = not in_code
            continue
        if in_code:
            continue
        heading = re.match(r"^###\s+(.+)", stripped)
        if heading:
            topic = plain(heading.group(1))[:40]
            if topic and topic not in topics and len(topics) < 3:
                topics.append(topic)
        if not stripped or re.match(r"^#{1,6}\s", stripped):
            continue
        cleaned = plain(re.sub(r"^(?:[-+]\s+|\d+[.)]\s+)", "", stripped))
        if cleaned:
            prose.append(cleaned)
    return " ".join(prose)[:160], topics
