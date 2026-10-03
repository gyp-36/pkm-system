"""Write content snapshots and bounded audit metadata in the caller's transaction."""

import uuid

from sqlalchemy.orm import Session

from app.enums import AuditAction, AuditActor, AuditEntityType
from app.models import AuditEvent, Note, NoteRevision


def record_revision(db: Session, note: Note, tag_ids: list[uuid.UUID]) -> None:
    db.add(NoteRevision(
        user_id=note.user_id,
        note_id=note.id,
        version=note.version,
        title=note.title,
        body_md=note.body_md,
        notebook_id=note.notebook_id,
        tag_ids=list(tag_ids),
    ))


def record_event(
    db: Session,
    user_id: uuid.UUID,
    action: AuditAction,
    entity_type: AuditEntityType,
    entity_id: uuid.UUID,
    *,
    entity_version: int | None = None,
    details: dict | None = None,
    actor_type: AuditActor = AuditActor.USER,
) -> None:
    safe_details = details or {}
    if set(safe_details) - {"fields", "affected_notes"}:
        raise ValueError("审计详情包含未登记字段")
    if "fields" in safe_details and (
        not isinstance(safe_details["fields"], list)
        or not all(field in {"title", "body_md", "notebook_id", "tag_ids", "taxonomy"} for field in safe_details["fields"])
    ):
        raise ValueError("审计字段名称无效")
    if "affected_notes" in safe_details and (not isinstance(safe_details["affected_notes"], int) or safe_details["affected_notes"] < 0):
        raise ValueError("审计计数无效")
    db.add(AuditEvent(
        user_id=user_id,
        actor_type=int(actor_type),
        action=int(action),
        entity_type=int(entity_type),
        entity_id=entity_id,
        entity_version=entity_version,
        details=safe_details,
    ))
