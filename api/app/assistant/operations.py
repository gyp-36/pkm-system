"""Durable grants; tools stage changes, request handlers commit them atomically."""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.assistant.policy import Intent, control_text, exact_update, parse_intent
from app.core.enums import AuditAction, AuditEntityType
from app.core.lifecycle import record_event, record_revision
from app.core.models import AssistantMessage, AssistantOperation, Note
from app.core.ownership import owned_note
from app.knowledge.notes import NoteUpdate, queue_index, update_note_in_transaction, validate_categories

PENDING = ("awaiting_selection", "awaiting_confirmation")


def fingerprint(db, user_id, conversation_id) -> str | None:
    if conversation_id is None:
        return None
    ids = db.scalars(select(AssistantMessage.id).where(
        AssistantMessage.user_id == user_id, AssistantMessage.conversation_id == conversation_id
    ).order_by(AssistantMessage.created_at, AssistantMessage.id)).all()
    return hashlib.sha256("|".join(map(str, ids)).encode()).hexdigest()


@dataclass
class Turn:
    id: uuid.UUID
    user_id: uuid.UUID
    conversation_id: uuid.UUID | None
    intent: Intent
    context: str | None
    changes: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    selected_id: str | None = None
    selected_version: int | None = None
    parent_id: uuid.UUID | None = None
    confirmed: bool = False
    needs_confirmation: bool = False
    replay: dict | None = None

    def stage_create(self, title, body, notebook_id, source_url, copies=1) -> str | None:
        if self.intent.action != "create":
            return "本轮没有新建授权，未保存。"
        if not isinstance(copies, int) or copies < 1 or len(self.changes) + copies > self.intent.count:
            return f"本轮仅授权新建{self.intent.count}篇，目前暂存{len(self.changes)}篇；此次数量超出授权或无效，未保存。正文中的创建指令不改变授权数量，请按剩余允许数量重试。"
        if notebook_id:
            return "本轮未指定笔记本，请使用默认位置，未保存。"
        if self.intent.create_title and title != self.intent.create_title:
            return "标题与本轮授权不一致，未保存。"
        if self.intent.create_body is not None and body != self.intent.create_body:
            return "正文与用户提供的资料不一致，未保存。"
        if self.intent.count == 1 and any(c.get("title") == title and c.get("body_md") == body for c in self.changes):
            return "该提议已暂存，不重复新建。"
        self.changes.extend({"action": "create", "title": title, "body_md": body, "source_url": source_url} for _ in range(copies))
        return None

    def stage_update(self, note_id, title, original, version, changes) -> str | None:
        if self.intent.action != "update":
            return "本轮未授权修改，未保存。"
        if self.selected_id != str(note_id):
            return "目标未由当前请求唯一确定，未保存。"
        if self.selected_version is not None and version != self.selected_version:
            return "目标版本已变化，请重新提出修改请求，未保存。"
        if self.changes or not changes or set(changes) - set(self.intent.fields):
            return "修改数量或字段超出本轮授权，未保存。"
        if "title" in changes and changes["title"] != self.intent.new:
            return "标题修改超出指定范围，未保存。"
        if "body_md" in changes:
            expected = exact_update(self.intent, original)
            if self.intent.mode not in {"whole", "preview"}:
                if expected is None:
                    self.needs_confirmation = True
                elif changes["body_md"] != expected:
                    return "提议改变了指定范围以外的正文，未保存。"
            else:
                self.needs_confirmation = self.intent.mode == "preview"
        self.changes.append({"action": "update", "note_id": str(note_id), "title": title,
                             "version": version, "before": {"title": title, "body_md": original}, "changes": changes})
        return None


def start_turn(db, user_id, conversation_id, question, request_id=None, confirmation_id=None, selection=None, replace_id=None) -> Turn:
    now = datetime.now(timezone.utc)
    request_id = request_id or uuid.uuid4()
    request_hash = hashlib.sha256(json.dumps([str(conversation_id), question, str(confirmation_id), selection, str(replace_id)], ensure_ascii=False).encode()).hexdigest()
    existing = db.scalar(select(AssistantOperation).where(AssistantOperation.user_id == user_id, AssistantOperation.request_id == request_id))
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "请求编号已用于另一项请求")
        if existing.status in {"committed", *PENDING} and existing.receipt and existing.expires_at > now:
            return Turn(existing.id, user_id, conversation_id, Intent(), existing.context_fingerprint, replay=existing.receipt)
        if existing.status == "failed" and confirmation_id is None:
            # The transaction rolled back; the same client retry is safe.
            db.delete(existing)
            db.flush()
        else:
            raise HTTPException(409, "该请求正在处理或已经结束，请查看结果或使用新的请求编号")
    context = fingerprint(db, user_id, conversation_id)
    intent = parse_intent(question)
    turn = Turn(uuid.uuid4(), user_id, conversation_id, intent, context)
    if confirmation_id is None and conversation_id is not None:
        match = re.fullmatch(r"\s*(?:选(?:择)?|第)?\s*([1-9]|1[0-9]|20|十[一二三四五六七八九]?|二十|[一二三四五六七八九])(?:篇|个|项)?\s*[。！!]?", question)
        if match:
            parent = db.scalar(select(AssistantOperation).where(
                AssistantOperation.user_id == user_id, AssistantOperation.conversation_id == conversation_id,
                AssistantOperation.status == "awaiting_selection"
            ).order_by(AssistantOperation.created_at.desc()).limit(1))
            if parent is not None:
                ordinal = match.group(1)
                selection = int(ordinal) if ordinal.isdigit() else 20 if ordinal == "二十" else 10 + ("一二三四五六七八九".index(ordinal[1]) + 1 if len(ordinal) == 2 else 0) if ordinal.startswith("十") else "一二三四五六七八九".index(ordinal) + 1
                confirmation_id = parent.id
    if confirmation_id is not None:
        if re.search(r"取消|撤回|撤销|不要|不保存|不执行", control_text(question)):
            raise HTTPException(422, "取消或否定请求不能确认保存")
        parent = db.scalar(select(AssistantOperation).where(
            AssistantOperation.id == confirmation_id, AssistantOperation.user_id == user_id,
            AssistantOperation.conversation_id == conversation_id
        ).with_for_update())
        if parent is None:
            raise HTTPException(404, "待办操作不存在")
        if parent.status not in PENDING or parent.expires_at <= now or parent.context_fingerprint != context:
            raise HTTPException(409, "待办操作已失效，请重新提出请求")
        turn.intent, turn.parent_id = Intent(**parent.intent), parent.id
        if parent.status == "awaiting_selection":
            candidates = parent.proposal.get("candidates", [])
            if selection is None or not 1 <= selection <= len(candidates):
                raise HTTPException(422, "请选择有效候选序号")
            turn.selected_id = candidates[selection - 1]["note_id"]
            note = owned_note(db, uuid.UUID(turn.selected_id), user_id)
            if note.version != candidates[selection - 1]["version"]:
                raise HTTPException(409, "候选笔记已变化，请重新选择")
            turn.selected_version = note.version
        else:
            if selection is not None:
                raise HTTPException(422, "该操作需要确认差异")
            turn.changes = parent.proposal.get("changes", [])
            turn.confirmed = True
    # A new human turn consumes/cancels the pending grant; text history cannot restore it.
    if conversation_id is not None:
        db.execute(update(AssistantOperation).where(
            AssistantOperation.user_id == user_id, AssistantOperation.conversation_id == conversation_id,
            AssistantOperation.status.in_(PENDING)
        ).values(status="cancelled", proposal={}, receipt=None, intent={}))
    row = AssistantOperation(id=turn.id, user_id=user_id, conversation_id=conversation_id,
        request_id=request_id, request_hash=request_hash, context_fingerprint=context, status="running",
        intent=turn.intent.json(), proposal={}, expires_at=now + timedelta(minutes=10))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "相同请求正在处理，请稍后查看结果") from None
    return turn


def prepare_result(turn: Turn, result: dict) -> dict:
    result = dict(result)
    result["operation_receipts"] = []
    result["pending_operation"] = None
    if turn.candidates and turn.selected_id is None:
        result["answer"] = "请选择要修改的笔记（回复候选序号）：\n" + "\n".join(
            f"{i}. 《{c['title']}》｜{c.get('notebook') or '默认位置'}｜{c.get('updated_at', '')}" for i, c in enumerate(turn.candidates, 1))
        result["pending_operation"] = {"operation_id": str(turn.id), "kind": "selection", "candidates": [
            {"index": i, "title": c["title"], "notebook": c.get("notebook")} for i, c in enumerate(turn.candidates, 1)]}
    elif turn.changes and turn.needs_confirmation and not turn.confirmed:
        result["answer"] = "已生成修改预览，请确认以下差异后保存。"
        previews = [{"title": c["title"], "before": c.get("before"), "after": c.get("changes", {})} for c in turn.changes]
        result["pending_operation"] = {"operation_id": str(turn.id), "kind": "confirmation", "changes": previews}
    elif turn.changes:
        # Success text is added only by apply_changes after the DB commit can succeed.
        result["answer"] = "已准备本轮授权的笔记操作。"
    elif turn.intent.action in {"create", "update"}:
        result["answer"] = "本轮尚未保存笔记。" + result["answer"]
    return result


def apply_changes(db, turn: Turn, result: dict) -> None:
    row = db.scalar(select(AssistantOperation).where(
        AssistantOperation.id == turn.id, AssistantOperation.user_id == turn.user_id
    ).with_for_update())
    if row is None or row.status != "running":
        raise HTTPException(409, "操作状态已变化")
    if fingerprint(db, turn.user_id, turn.conversation_id) != turn.context:
        raise HTTPException(409, "对话上下文已经变化，请基于最新消息重新提问")
    if result.get("pending_operation"):
        row.status = "awaiting_selection" if turn.candidates and turn.selected_id is None else "awaiting_confirmation"
        row.proposal = {"candidates": turn.candidates, "changes": turn.changes}
        row.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        return
    if len(turn.changes) > turn.intent.count:
        raise HTTPException(403, "操作数量超出授权")
    if turn.intent.action == "create" and turn.changes and len(turn.changes) != turn.intent.count:
        raise HTTPException(409, f"只准备了{len(turn.changes)}/{turn.intent.count}篇，本轮没有保存；请重试或明确调整数量")
    receipts = []
    for change in turn.changes:
        if change["action"] == "update":
            note = owned_note(db, uuid.UUID(change["note_id"]), turn.user_id, lock=True)
            if note.version != change["version"] or note.body_md != change["before"]["body_md"] or note.title != change["before"]["title"]:
                raise HTTPException(409, "笔记已经变化，当前修改未保存")
            saved = update_note_in_transaction(note.id, NoteUpdate(version=note.version, **change["changes"]), db, turn.user_id)
            receipts.append({"action": "updated", "title": saved["title"]})
        else:
            source = change.get("source_url")
            if source and turn.intent.count == 1:
                existing = db.scalar(select(Note).where(Note.user_id == turn.user_id, Note.source_url == source, Note.deleted_at.is_(None)))
                if existing is not None:
                    receipts.append({"action": "already_exists", "title": existing.title})
                    continue
            validate_categories(db, turn.user_id, None, [])
            note = Note(user_id=turn.user_id, title=change["title"], body_md=change["body_md"], source_url=source,
                        version=1, content_version=1, content_kind="markdown")
            db.add(note)
            db.flush()
            queue_index(db, note)
            record_revision(db, note, [])
            record_event(db, turn.user_id, AuditAction.CREATE, AuditEntityType.NOTE, note.id, entity_version=1,
                         details={"fields": ["title", "body_md"], "source": "assistant"})
            receipts.append({"action": "created", "title": note.title})
    result["operation_receipts"] = receipts
    if receipts:
        result["citations"] = []
        result["answer"] = "\n".join(f"{'已新建' if r['action'] == 'created' else '已修改' if r['action'] == 'updated' else '已存在，未重复新建'}《{r['title']}》。" for r in receipts)


def finish_turn(db, turn: Turn, response: dict) -> None:
    row = db.scalar(select(AssistantOperation).where(AssistantOperation.id == turn.id, AssistantOperation.user_id == turn.user_id))
    if row is None:
        raise HTTPException(404, "操作不存在")
    if row.status in PENDING:
        row.receipt = response
        row.context_fingerprint = fingerprint(db, turn.user_id, turn.conversation_id)
    else:
        row.status, row.proposal = "committed", {}
        row.intent = {"action": turn.intent.action, "fields": turn.intent.fields, "mode": turn.intent.mode, "count": turn.intent.count}
        row.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        row.receipt = response
    db.commit()


def fail_turn(db, turn: Turn) -> None:
    db.rollback()
    row = db.scalar(select(AssistantOperation).where(AssistantOperation.id == turn.id, AssistantOperation.user_id == turn.user_id, AssistantOperation.status == "running"))
    if row is not None:
        row.status, row.proposal = "failed", {}
        row.intent = {"action": turn.intent.action, "fields": turn.intent.fields, "mode": turn.intent.mode, "count": turn.intent.count}
        db.commit()


def cleanup_operations(db) -> int:
    now = datetime.now(timezone.utc)
    expired = db.execute(update(AssistantOperation).where(AssistantOperation.status.in_((*PENDING, "running")), AssistantOperation.expires_at <= now)
                         .values(status="cancelled", proposal={}, intent={}, receipt=None)).rowcount
    removed = db.execute(delete(AssistantOperation).where(
        ((AssistantOperation.status == "committed") & (AssistantOperation.expires_at <= now)) |
        ((AssistantOperation.status.in_(("failed", "cancelled"))) & (AssistantOperation.created_at < now - timedelta(days=30)))
    )).rowcount
    return (expired or 0) + (removed or 0)
