"""Account-owned, single-level notebooks and tags."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.auth import Db, UserId
from app.core.enums import AuditAction, AuditEntityType
from app.core.lifecycle import record_event, record_revision
from app.core.models import Note, Notebook, NoteTag, Tag
from app.core.ownership import owned_notebook, owned_tag
from app.contracts.taxonomy import ClassificationOut


router = APIRouter(prefix="/v1", tags=["taxonomy"])


class NameInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("名称不能为空")
        return value


def item_json(item: Notebook | Tag, note_count: int | None = None) -> dict[str, str | int]:
    value: dict[str, str | int] = {"id": str(item.id), "name": item.name}
    if note_count is not None:
        value["note_count"] = note_count
    return value


def save_name(db: Db, item: Notebook | Tag, action: AuditAction) -> dict[str, str]:
    try:
        db.flush()
        record_event(db, item.user_id, action, AuditEntityType.NOTEBOOK if isinstance(item, Notebook) else AuditEntityType.TAG, item.id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="名称已存在") from exc
    return item_json(item)


@router.get("/notebooks", response_model=list[ClassificationOut])
def list_notebooks(db: Db, user_id: UserId) -> list[dict[str, str | int]]:
    rows = db.execute(
        select(Notebook, func.count(Note.id))
        .outerjoin(Note, (Note.notebook_id == Notebook.id) & (Note.user_id == user_id) & Note.deleted_at.is_(None))
        .where(Notebook.user_id == user_id, Notebook.deleted_at.is_(None))
        .group_by(Notebook.id)
        .order_by(Notebook.name)
    ).all()
    return [item_json(item, count) for item, count in rows]


@router.get("/notebooks/{item_id}", response_model=ClassificationOut)
def get_notebook(item_id: uuid.UUID, db: Db, user_id: UserId) -> dict[str, str]:
    return item_json(owned_notebook(db, item_id, user_id))


@router.post("/notebooks", status_code=201, response_model=ClassificationOut)
def create_notebook(body: NameInput, db: Db, user_id: UserId) -> dict[str, str]:
    if len(body.name) > 120:
        raise HTTPException(status_code=422, detail="名称过长")
    item = Notebook(user_id=user_id, name=body.name)
    db.add(item)
    return save_name(db, item, AuditAction.CREATE)


@router.patch("/notebooks/{item_id}", response_model=ClassificationOut)
def rename_notebook(item_id: uuid.UUID, body: NameInput, db: Db, user_id: UserId) -> dict[str, str]:
    item = owned_notebook(db, item_id, user_id)
    item.name = body.name
    return save_name(db, item, AuditAction.RENAME)


@router.delete("/notebooks/{item_id}", status_code=204)
def delete_notebook(item_id: uuid.UUID, db: Db, user_id: UserId) -> None:
    item = owned_notebook(db, item_id, user_id)
    item.deleted_at = datetime.now(timezone.utc)
    notes = db.scalars(select(Note).where(Note.user_id == user_id, Note.notebook_id == item_id, Note.deleted_at.is_(None)).order_by(Note.id).with_for_update()).all()
    for note in notes:
        note.notebook_id = None
        record_category_change(db, note)
    record_event(db, user_id, AuditAction.DELETE, AuditEntityType.NOTEBOOK, item.id, details={"affected_notes": len(notes)})
    db.commit()


@router.get("/tags", response_model=list[ClassificationOut])
def list_tags(db: Db, user_id: UserId) -> list[dict[str, str]]:
    return [item_json(item) for item in db.scalars(select(Tag).where(Tag.user_id == user_id, Tag.deleted_at.is_(None)).order_by(Tag.name))]


@router.get("/tags/{item_id}", response_model=ClassificationOut)
def get_tag(item_id: uuid.UUID, db: Db, user_id: UserId) -> dict[str, str]:
    return item_json(owned_tag(db, item_id, user_id))


@router.post("/tags", status_code=201, response_model=ClassificationOut)
def create_tag(body: NameInput, db: Db, user_id: UserId) -> dict[str, str]:
    if len(body.name) > 80:
        raise HTTPException(status_code=422, detail="标签名称过长")
    item = Tag(user_id=user_id, name=body.name)
    db.add(item)
    return save_name(db, item, AuditAction.CREATE)


@router.patch("/tags/{item_id}", response_model=ClassificationOut)
def rename_tag(item_id: uuid.UUID, body: NameInput, db: Db, user_id: UserId) -> dict[str, str]:
    if len(body.name) > 80:
        raise HTTPException(status_code=422, detail="标签名称过长")
    item = owned_tag(db, item_id, user_id)
    item.name = body.name
    return save_name(db, item, AuditAction.RENAME)


@router.delete("/tags/{item_id}", status_code=204)
def delete_tag(item_id: uuid.UUID, db: Db, user_id: UserId) -> None:
    item = owned_tag(db, item_id, user_id)
    item.deleted_at = datetime.now(timezone.utc)
    note_ids = select(NoteTag.note_id).where(NoteTag.user_id == user_id, NoteTag.tag_id == item_id)
    notes = db.scalars(select(Note).where(Note.user_id == user_id, Note.id.in_(note_ids), Note.deleted_at.is_(None)).order_by(Note.id).with_for_update()).all()
    db.execute(delete(NoteTag).where(NoteTag.user_id == user_id, NoteTag.tag_id == item_id))
    for note in notes:
        record_category_change(db, note)
    record_event(db, user_id, AuditAction.DELETE, AuditEntityType.TAG, item.id, details={"affected_notes": len(notes)})
    db.commit()


def record_category_change(db: Db, note: Note) -> None:
    note.version += 1
    note.updated_at = datetime.now(timezone.utc)
    tag_ids = db.scalars(select(NoteTag.tag_id).where(NoteTag.user_id == note.user_id, NoteTag.note_id == note.id)).all()
    record_revision(db, note, tag_ids)
    record_event(db, note.user_id, AuditAction.UPDATE, AuditEntityType.NOTE, note.id, entity_version=note.version, details={"fields": ["taxonomy"]})
