"""Write content snapshots and bounded audit metadata in the caller's transaction."""

import logging
import uuid

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.enums import AuditAction, AuditActor, AuditEntityType, AuditOutcome
from app.core.models import AuditEvent, Note, NoteRevision
from app.core.request_context import current_actor_id, current_request_id


log = logging.getLogger(__name__)


AUDIT_FIELDS = {"title", "body_md", "notebook_id", "tag_ids", "taxonomy", "content_kind", "source_url"}
AUDIT_SOURCES = {"assistant", "system", "worker", "onlyoffice"}


def _validate_details(details: dict) -> None:
    """Validate registered detail keys; unknown keys pass through.

    未登记键只放行、不抛错。审计属于旁路逻辑，任何约束都不应击穿调用方的事务。

    `fields` 是笔记专属的受控键，值域固定；其他实体用 `changed` 记录变更字段名，
    只做标识符形状校验，不限制具体取值。
    """
    if "fields" in details and (
        not isinstance(details["fields"], list)
        or not all(field in AUDIT_FIELDS for field in details["fields"])
    ):
        raise ValueError("审计字段名称无效")
    if "affected_notes" in details and (
        not isinstance(details["affected_notes"], int) or details["affected_notes"] < 0
    ):
        raise ValueError("审计计数无效")
    if "changed" in details and (
        not isinstance(details["changed"], list)
        or not all(isinstance(field, str) and field.isidentifier() for field in details["changed"])
    ):
        raise ValueError("审计变更字段名无效")
    if "source" in details and details["source"] not in AUDIT_SOURCES:
        raise ValueError("审计来源标记无效")


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
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
) -> None:
    """写入一条业务审计。

    `request_id` 与 `actor_id` 从请求上下文自动获取，调用方无需传递；
    在后台任务等无请求上下文场景下自动为空。

    注意：本函数把审计行加入**调用方的事务**，因此业务回滚会一并撤销它。
    需要「即使失败也留痕」的场景由 `app.ops.audit_middleware` 用独立会话处理。
    """
    safe_details = dict(details or {})
    _validate_details(safe_details)
    actor_id = current_actor_id()
    if actor_id is None and actor_type == AuditActor.USER:
        actor_id = user_id
    db.add(AuditEvent(
        user_id=user_id,
        actor_type=int(actor_type),
        action=int(action),
        entity_type=int(entity_type),
        entity_id=entity_id,
        entity_version=entity_version,
        details=safe_details,
        request_id=current_request_id(),
        actor_id=actor_id,
        outcome=int(outcome),
    ))


def record_failure_isolated(
    *,
    user_id: uuid.UUID,
    action: AuditAction,
    entity_type: AuditEntityType,
    entity_id: uuid.UUID,
    details: dict | None = None,
    actor_type: AuditActor = AuditActor.USER,
) -> None:
    """用独立会话补记一条失败审计。

    用于「业务代码已经知道失败原因，而中间件拿不到用户身份」的场景——
    典型例子是登录密码错误：该请求不携带有效会话 Cookie，
    中间件无法把这次尝试归属到任何用户，只能在访问日志里留下一条匿名 401。

    审计是旁路逻辑，因此任何异常都在内部吞掉，绝不上抛给业务。
    """
    try:
        with SessionLocal() as db:
            db.add(AuditEvent(
                user_id=user_id,
                actor_type=int(actor_type),
                action=int(action),
                entity_type=int(entity_type),
                entity_id=entity_id,
                details=dict(details or {}),
                # 独立会话只影响事务边界，不应丢掉请求上下文：
                # 带上 request_id 才能与同一次请求的访问日志互相印证。
                request_id=current_request_id(),
                actor_id=user_id if actor_type == AuditActor.USER else None,
                outcome=int(AuditOutcome.FAILED),
            ))
            db.commit()
    except Exception:  # noqa: BLE001 - 旁路逻辑，绝不上抛
        log.warning("isolated failure audit write failed", exc_info=True)
