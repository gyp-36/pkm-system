"""Account-owned Markdown templates for creating notes."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.auth import Db, UserId
from app.core.enums import AuditAction, AuditEntityType
from app.core.lifecycle import record_event
from app.core.models import NoteTemplate


router = APIRouter(prefix="/v1/note-templates", tags=["note-templates"])


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=240)
    body_md: str = Field(default="", max_length=100_000)

    @field_validator("name", "title")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("名称和标题不能为空")
        return value


class TemplateRename(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("模板名称不能为空")
        return value


def template_json(item: NoteTemplate) -> dict:
    return {
        "id": str(item.id),
        "name": item.name,
        "title": item.title,
        "body_md": item.body_md,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


@router.get("")
def list_templates(db: Db, user_id: UserId) -> list[dict]:
    rows = db.scalars(
        select(NoteTemplate)
        .where(NoteTemplate.user_id == user_id)
        .order_by(NoteTemplate.updated_at.desc(), NoteTemplate.name.asc())
    ).all()
    return [template_json(item) for item in rows]


@router.post("", status_code=201)
def create_template(body: TemplateCreate, db: Db, user_id: UserId) -> dict:
    item = NoteTemplate(user_id=user_id, name=body.name, title=body.title, body_md=body.body_md)
    db.add(item)
    db.flush()
    record_event(db, user_id, AuditAction.CREATE, AuditEntityType.TEMPLATE, item.id,
                 details={"changed": ["name", "title", "body_md"]})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="模板名称已存在") from exc
    db.refresh(item)
    return template_json(item)


@router.patch("/{template_id}")
def rename_template(template_id: uuid.UUID, body: TemplateRename, db: Db, user_id: UserId) -> dict:
    item = db.scalar(
        select(NoteTemplate).where(NoteTemplate.id == template_id, NoteTemplate.user_id == user_id).with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    item.name = body.name
    item.updated_at = datetime.now(timezone.utc)
    record_event(db, user_id, AuditAction.RENAME, AuditEntityType.TEMPLATE, item.id,
                 details={"changed": ["name"]})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="模板名称已存在") from exc
    db.refresh(item)
    return template_json(item)


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: uuid.UUID, db: Db, user_id: UserId) -> None:
    item = db.scalar(
        select(NoteTemplate).where(NoteTemplate.id == template_id, NoteTemplate.user_id == user_id).with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    record_event(db, user_id, AuditAction.DELETE, AuditEntityType.TEMPLATE, item.id)
    db.delete(item)
    db.commit()
