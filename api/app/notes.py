"""Versioned Markdown notes with account checks and durable index jobs."""

import io
import json
import re
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, delete, or_, select
from starlette.responses import Response

from app.auth import Db, UserId
from app.enums import AuditAction, AuditEntityType, IndexJobStatus, NoteIndexStatus
from app.lifecycle import record_event, record_revision
from app.models import IndexJob, Note, NoteChunk, Notebook, NoteTag, Tag


router = APIRouter(prefix="/v1/notes", tags=["notes"])
INDEX_DEBOUNCE_SECONDS = 8


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    body_md: str = Field(default="", max_length=100_000)
    notebook_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("标题不能为空")
        return value


class NoteUpdate(BaseModel):
    version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    body_md: str | None = Field(default=None, max_length=100_000)
    notebook_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("标题不能为空")
        return value


def note_json(db: Db, note: Note, include_body: bool = True) -> dict:
    tag_ids = db.scalars(select(NoteTag.tag_id).where(NoteTag.note_id == note.id, NoteTag.user_id == note.user_id)).all()
    excerpt = re.sub(r"!\[[^]]*\]\([^)]*\)", "", note.body_md)
    excerpt = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", excerpt)
    excerpt = re.sub(r"[`*_>#~\[\]]", " ", excerpt)
    excerpt = re.sub(r"\s+", " ", excerpt).strip()[:160]
    result = {
        "id": str(note.id),
        "title": note.title,
        "excerpt": excerpt,
        "notebook_id": str(note.notebook_id) if note.notebook_id else None,
        "tag_ids": [str(item) for item in tag_ids],
        "version": note.version,
        "index_status": NoteIndexStatus(note.index_status).name.lower(),
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
    }
    if include_body:
        result["body_md"] = note.body_md
    return result


def owned_note(db: Db, note_id: uuid.UUID, user_id: uuid.UUID, lock: bool = False) -> Note:
    query = select(Note).where(Note.id == note_id, Note.user_id == user_id, Note.deleted_at.is_(None))
    if lock:
        query = query.with_for_update()
    note = db.scalar(query)
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return note


def validate_categories(db: Db, user_id: uuid.UUID, notebook_id: uuid.UUID | None, tag_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    if notebook_id is not None and db.scalar(select(Notebook.id).where(Notebook.id == notebook_id, Notebook.user_id == user_id, Notebook.deleted_at.is_(None)).with_for_update()) is None:
        raise HTTPException(status_code=404, detail="笔记本不存在")
    distinct = list(dict.fromkeys(tag_ids))
    if distinct:
        found = set(db.scalars(select(Tag.id).where(Tag.user_id == user_id, Tag.id.in_(distinct), Tag.deleted_at.is_(None)).order_by(Tag.id).with_for_update()).all())
        if found != set(distinct):
            raise HTTPException(status_code=404, detail="标签不存在")
    return distinct


def replace_tags(db: Db, note: Note, tag_ids: list[uuid.UUID]) -> None:
    db.execute(delete(NoteTag).where(NoteTag.note_id == note.id, NoteTag.user_id == note.user_id))
    db.add_all(NoteTag(note_id=note.id, tag_id=tag_id, user_id=note.user_id) for tag_id in tag_ids)


def queue_index(db: Db, note: Note) -> None:
    now = datetime.now(timezone.utc)
    job = db.scalar(
        select(IndexJob)
        .where(
            IndexJob.note_id == note.id,
            IndexJob.status.in_((IndexJobStatus.PENDING, IndexJobStatus.PROCESSING)),
        )
        .with_for_update()
    )
    if job is None:
        db.add(IndexJob(
            user_id=note.user_id,
            note_id=note.id,
            target_version=note.content_version,
            status=IndexJobStatus.PENDING,
            available_at=now + timedelta(seconds=INDEX_DEBOUNCE_SECONDS),
        ))
    else:
        # Coalesce rapid edits into one delayed job targeting the newest content.
        job.target_version = note.content_version
        job.status = IndexJobStatus.PENDING
        job.attempts = 0
        job.last_error = None
        job.available_at = now + timedelta(seconds=INDEX_DEBOUNCE_SECONDS)
        job.updated_at = now
    note.index_status = NoteIndexStatus.PENDING


def safe_filename(value: str, fallback: str = "note") -> str:
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value).strip(" .")
    return (value or fallback)[:100]


def markdown_export(note: Note, notebook_name: str | None, tag_names: list[str]) -> str:
    # JSON string literals are valid YAML scalars, so titles and tags containing
    # quotes, colons, or newlines remain safe in common Markdown front matter.
    notebook_value = "null" if notebook_name is None else json.dumps(notebook_name, ensure_ascii=False)
    tags_value = json.dumps(tag_names, ensure_ascii=False)
    front_matter = (
        "---\n"
        f"id: {json.dumps(str(note.id))}\n"
        f"title: {json.dumps(note.title, ensure_ascii=False)}\n"
        f"notebook: {notebook_value}\n"
        f"tags: {tags_value}\n"
        f"version: {note.version}\n"
        f"created_at: {json.dumps(note.created_at.isoformat())}\n"
        f"updated_at: {json.dumps(note.updated_at.isoformat())}\n"
        "---\n\n"
    )
    return front_matter + note.body_md


def download_response(content: str | bytes, filename: str, media_type: str) -> Response:
    disposition = f"attachment; filename*=UTF-8''{quote(filename, safe='')}"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": disposition})


@router.get("")
def list_notes(
    db: Db,
    user_id: UserId,
    limit: int = Query(default=30, ge=1, le=100),
    cursor: uuid.UUID | None = None,
    notebook_id: uuid.UUID | None = None,
    unclassified: bool = False,
    tag_id: uuid.UUID | None = None,
    search_tag_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=150),
    q_scope: Literal["all", "title", "tag"] | None = None,
    updated_desc: bool = True,
) -> dict:
    query = select(Note).where(Note.user_id == user_id, Note.deleted_at.is_(None))
    if unclassified:
        query = query.where(Note.notebook_id.is_(None))
    elif notebook_id is not None:
        query = query.where(Note.notebook_id == notebook_id)
    if tag_id is not None:
        query = query.where(
            Note.id.in_(select(NoteTag.note_id).where(NoteTag.user_id == user_id, NoteTag.tag_id == tag_id))
        )
    if search_tag_id is not None:
        query = query.where(
            Note.id.in_(select(NoteTag.note_id).where(NoteTag.user_id == user_id, NoteTag.tag_id == search_tag_id))
        )
    if q:
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        title_match = Note.title.ilike(pattern, escape="\\")
        if q_scope == "title":
            query = query.where(title_match)
        elif q_scope in ("all", "tag"):
            matching_tags = (
                select(NoteTag.note_id)
                .join(Tag, and_(Tag.id == NoteTag.tag_id, Tag.user_id == user_id, Tag.deleted_at.is_(None)))
                .where(NoteTag.user_id == user_id, Tag.name.ilike(pattern, escape="\\"))
            )
            query = query.where(Note.id.in_(matching_tags) if q_scope == "tag" else or_(title_match, Note.id.in_(matching_tags)))
        else:
            query = query.where(or_(title_match, Note.body_md.ilike(pattern, escape="\\")))
    if cursor is not None:
        cursor_note = db.scalar(select(Note).where(Note.id == cursor, Note.user_id == user_id, Note.deleted_at.is_(None)))
        if cursor_note is None:
            raise HTTPException(status_code=400, detail="无效的列表游标")
        older = Note.updated_at < cursor_note.updated_at if updated_desc else Note.updated_at > cursor_note.updated_at
        tied = and_(Note.updated_at == cursor_note.updated_at, Note.id < cursor if updated_desc else Note.id > cursor)
        query = query.where(or_(older, tied))
    query = query.order_by(Note.updated_at.desc() if updated_desc else Note.updated_at.asc(), Note.id.desc() if updated_desc else Note.id.asc())
    notes = db.scalars(query.limit(limit + 1)).all()
    page = notes[:limit]
    return {"items": [note_json(db, note, include_body=False) for note in page], "next_cursor": str(page[-1].id) if len(notes) > limit else None}


@router.get("/export")
def export_all_notes(db: Db, user_id: UserId) -> Response:
    rows = db.execute(
        select(Note, Notebook.name)
        .outerjoin(Notebook, and_(Notebook.id == Note.notebook_id, Notebook.user_id == user_id, Notebook.deleted_at.is_(None)))
        .where(Note.user_id == user_id, Note.deleted_at.is_(None))
        .order_by(Notebook.name.asc().nullsfirst(), Note.title.asc(), Note.id.asc())
    ).all()
    note_ids = [note.id for note, _ in rows]
    tags_by_note: dict[uuid.UUID, list[str]] = {note_id: [] for note_id in note_ids}
    if note_ids:
        tag_rows = db.execute(
            select(NoteTag.note_id, Tag.name)
            .join(Tag, and_(Tag.id == NoteTag.tag_id, Tag.user_id == user_id, Tag.deleted_at.is_(None)))
            .where(NoteTag.user_id == user_id, NoteTag.note_id.in_(note_ids))
            .order_by(Tag.name.asc())
        ).all()
        for note_id, tag_name in tag_rows:
            tags_by_note[note_id].append(tag_name)

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "README.md",
            "# PKM Markdown 导出\n\n"
            "每篇笔记保存在独立的 `.md` 文件中。文件开头的 YAML front matter 保存笔记 ID、"
            "标题、笔记本、标签、版本和时间；正文保持 Markdown 原文。\n",
        )
        used_paths: set[str] = set()
        for note, notebook_name in rows:
            folder = safe_filename(notebook_name, "未分类") if notebook_name else "未分类"
            filename = f"{safe_filename(note.title)}-{str(note.id)[:8]}.md"
            path = f"{folder}/{filename}"
            if path in used_paths:
                path = f"{folder}/{safe_filename(note.title)}-{note.id}.md"
            used_paths.add(path)
            bundle.writestr(path, markdown_export(note, notebook_name, tags_by_note[note.id]))
    archive.seek(0)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return download_response(archive.getvalue(), f"pkm-notes-{stamp}.zip", "application/zip")


@router.post("", status_code=201)
def create_note(body: NoteCreate, db: Db, user_id: UserId) -> dict:
    tag_ids = validate_categories(db, user_id, body.notebook_id, body.tag_ids)
    note = Note(user_id=user_id, notebook_id=body.notebook_id, title=body.title, body_md=body.body_md, version=1)
    db.add(note)
    db.flush()
    replace_tags(db, note, tag_ids)
    queue_index(db, note)
    record_revision(db, note, tag_ids)
    record_event(db, user_id, AuditAction.CREATE, AuditEntityType.NOTE, note.id, entity_version=note.version)
    db.commit()
    db.refresh(note)
    return note_json(db, note)


@router.get("/{note_id}")
def get_note(note_id: uuid.UUID, db: Db, user_id: UserId) -> dict:
    return note_json(db, owned_note(db, note_id, user_id))


@router.get("/{note_id}/export")
def export_note(note_id: uuid.UUID, db: Db, user_id: UserId) -> Response:
    note = owned_note(db, note_id, user_id)
    notebook_name = None
    if note.notebook_id is not None:
        notebook_name = db.scalar(
            select(Notebook.name).where(
                Notebook.id == note.notebook_id,
                Notebook.user_id == user_id,
                Notebook.deleted_at.is_(None),
            )
        )
    tag_names = db.scalars(
        select(Tag.name)
        .join(NoteTag, and_(NoteTag.tag_id == Tag.id, NoteTag.user_id == user_id))
        .where(NoteTag.note_id == note.id, Tag.user_id == user_id, Tag.deleted_at.is_(None))
        .order_by(Tag.name.asc())
    ).all()
    filename = f"{safe_filename(note.title)}-{str(note.id)[:8]}.md"
    return download_response(markdown_export(note, notebook_name, list(tag_names)), filename, "text/markdown; charset=utf-8")


@router.patch("/{note_id}")
def update_note(note_id: uuid.UUID, body: NoteUpdate, db: Db, user_id: UserId) -> dict:
    note = owned_note(db, note_id, user_id, lock=True)
    if note.version != body.version:
        raise HTTPException(status_code=409, detail="笔记已有新版本，请刷新后重试")
    old_title, old_body = note.title, note.body_md
    if "title" in body.model_fields_set:
        if body.title is None:
            raise HTTPException(status_code=422, detail="标题不能为空")
        note.title = body.title
    if "body_md" in body.model_fields_set:
        if body.body_md is None:
            raise HTTPException(status_code=422, detail="正文不能为空")
        note.body_md = body.body_md
    notebook_id = body.notebook_id if "notebook_id" in body.model_fields_set else note.notebook_id
    tag_ids = body.tag_ids if "tag_ids" in body.model_fields_set else db.scalars(select(NoteTag.tag_id).where(NoteTag.note_id == note.id, NoteTag.user_id == user_id)).all()
    if tag_ids is None:
        raise HTTPException(status_code=422, detail="标签列表不能为空")
    tag_ids = validate_categories(db, user_id, notebook_id, tag_ids)
    note.notebook_id = notebook_id
    replace_tags(db, note, tag_ids)
    note.version += 1
    note.updated_at = datetime.now(timezone.utc)
    content_changed = note.title != old_title or note.body_md != old_body
    if content_changed:
        note.content_version += 1
        queue_index(db, note)
    record_revision(db, note, tag_ids)
    record_event(db, user_id, AuditAction.UPDATE, AuditEntityType.NOTE, note.id, entity_version=note.version, details={"fields": sorted(body.model_fields_set - {"version"})})
    db.commit()
    db.refresh(note)
    return note_json(db, note)


@router.delete("/{note_id}", status_code=204)
def delete_note(note_id: uuid.UUID, db: Db, user_id: UserId, version: int = Query(ge=1)) -> None:
    note = owned_note(db, note_id, user_id, lock=True)
    if note.version != version:
        raise HTTPException(status_code=409, detail="笔记已有新版本，请刷新后重试")
    note.deleted_at = datetime.now(timezone.utc)
    note.updated_at = note.deleted_at
    record_event(db, user_id, AuditAction.DELETE, AuditEntityType.NOTE, note.id, entity_version=note.version)
    db.commit()
