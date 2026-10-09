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

from app.assistant.policy import Intent, control_text, exact_update, paragraph_range, parse_intent, request_parts
from app.core.enums import AuditAction, AuditEntityType
from app.core.lifecycle import record_event, record_revision
from app.core.models import AssistantMessage, AssistantOperation, Note
from app.core.ownership import owned_note
from app.knowledge.notes import NoteUpdate, queue_index, update_note_in_transaction, validate_categories

PENDING = ("awaiting_selection", "awaiting_confirmation", "awaiting_input")
REPLAYABLE = ("committed", "completed", "drafted", *PENDING)
CONFIRM_TEXT = re.compile(r"^(?:可以|好的|好|确认|确认保存(?:上述|这些)?差异|确认保存|直接创建|直接保存|保存|创建|重新写入|写回)[。！!]?$")


def draft_choice(question: str) -> int | None:
    match = re.fullmatch(r"\s*(?:选(?:择)?|用|第)?\s*([1-9]|1[0-9]|20|[A-Ea-e]|十[一二三四五六七八九]?|二十|[一二三四五六七八九])(?:篇|个|项|版)?(?:替换|写入|保存)?\s*[。！!]?", question)
    if not match:
        return None
    value = match.group(1)
    if value.isdigit():
        return int(value)
    if value.isascii():
        return ord(value.upper()) - ord("A") + 1
    return 20 if value == "二十" else 10 + ("一二三四五六七八九".index(value[1]) + 1 if len(value) == 2 else 0) if value.startswith("十") else "一二三四五六七八九".index(value) + 1


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
    drafts: list[dict] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)
    draft_started: bool = False

    def prepare_draft(self, title: str, body: str, label: str = "") -> str | None:
        if not title.strip() or not body.strip() or len(title) > 240 or len(body.encode()) > 60_000:
            return "草稿标题或正文无效，请缩短后重试。"
        if self.parent_id is not None and self.intent.draft_requested and not self.draft_started:
            self.drafts = []
        self.draft_started = True
        if len(self.drafts) >= 5:
            return "本轮最多准备五个草稿版本。"
        item = {"title": title.strip(), "body_md": body, "label": label[:40],
                "sha256": hashlib.sha256(body.encode()).hexdigest()}
        if item not in self.drafts:
            self.drafts.append(item)
        return None

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

    def stage_update(self, note_id, title, original, version, changes, *, variant: str | None = None) -> str | None:
        if self.intent.action != "update":
            return "本轮未授权修改，未保存。"
        if self.selected_id != str(note_id):
            return "目标未由当前请求唯一确定，未保存。"
        if self.selected_version is not None and version != self.selected_version:
            return "目标版本已变化，请重新提出修改请求，未保存。"
        if self.changes or (self.alternatives and not variant) or not changes or set(changes) - set(self.intent.fields):
            return "修改数量或字段超出本轮授权，未保存。"
        if "title" in changes and changes["title"] != self.intent.new:
            return "标题修改超出指定范围，未保存。"
        if "body_md" in changes:
            body = changes["body_md"]
            if self.intent.scope and self.intent.scope.startswith("paragraph:"):
                region = paragraph_range(original, int(self.intent.scope.split(":")[1]))
                if region is None:
                    return "找不到指定段落，未保存。"
                start, end = region
                prefix, suffix = original[:start], original[end:]
                if not body.startswith(prefix) or not body.endswith(suffix) or len(body) < len(prefix) + len(suffix):
                    return "提议改变了指定段落以外的正文，未保存。"
            elif self.intent.scope == "append" and not body.startswith(original):
                return "追加只能增加结尾内容，不能改动原文，未保存。"
            elif self.intent.scope == "prepend" and not body.endswith(original):
                return "添加只能增加开头内容，不能改动原文，未保存。"
            expected = exact_update(self.intent, original)
            if self.intent.mode not in {"whole", "preview"}:
                if expected is None:
                    self.needs_confirmation = True
                elif changes["body_md"] != expected:
                    return "提议改变了指定范围以外的正文，未保存。"
            else:
                self.needs_confirmation = self.intent.mode == "preview"
        proposal = {"action": "update", "note_id": str(note_id), "title": title,
                    "version": version, "before": {"title": title, "body_md": original}, "changes": changes}
        if variant:
            if len(self.alternatives) >= 5 or any(a["label"].casefold() == variant.strip().casefold() for a in self.alternatives):
                return "版本名称重复或版本数量超出限制，未保存。"
            self.alternatives.append({"label": variant.strip()[:40], "change": proposal})
        else:
            self.changes.append(proposal)
        return None


def _verified_drafts(proposal: dict) -> list[dict]:
    return [d for d in proposal.get("drafts", []) if isinstance(d, dict)
            and isinstance(d.get("title"), str) and isinstance(d.get("body_md"), str)
            and hashlib.sha256(d["body_md"].encode()).hexdigest() == d.get("sha256")]


def _resume_input(turn: Turn, parent, question: str) -> bool:
    """Continue only a live server task; assistant/history prose grants nothing."""
    current = turn.intent
    prior = Intent(**parent.intent)
    directive, body = request_parts(question)
    if parent.status == "awaiting_input" and prior.action == "create":
        if body is not None or CONFIRM_TEXT.fullmatch(control_text(question).strip()):
            turn.intent = prior
            if body is not None:
                from app.assistant.policy import _unquote
                turn.intent.create_body = _unquote(body)
                turn.intent.missing = []
                if not turn.intent.create_title:
                    heading = re.match(r"\s*#\s+([^\n]+)", turn.intent.create_body)
                    if heading:
                        turn.intent.create_title = heading.group(1).strip()
            turn.drafts = _verified_drafts(parent.proposal)
            return True
    if parent.status == "awaiting_input" and prior.action == "update" and "target_title" in prior.missing:
        title = question.strip().strip("《》")
        if current.action == "none" and 0 < len(title) <= 120 and not re.search(r"[\n？?]|取消|撤回|不执行|不要|解释|根据|授权|规则|换个话题|你好", title):
            turn.intent = prior
            turn.intent.target_title, turn.intent.missing = title, []
            return True
    if current.action == "create" and current.create_body is None:
        drafts = _verified_drafts(parent.proposal)
        if drafts:
            turn.drafts = drafts
            turn.intent.missing = []
            if len(drafts) == 1:
                turn.intent.create_title = current.create_title or drafts[0]["title"]
                turn.intent.create_body = drafts[0]["body_md"]
            return True
    if parent.status == "drafted" and current.action == "none":
        choice = draft_choice(question)
        drafts = _verified_drafts(parent.proposal)
        if drafts and (choice is not None or re.fullmatch(r"(?:就这样|不需要|不用调整|可以|好的|好)[。！!]?", question.strip())):
            if choice is not None and not 1 <= choice <= len(drafts):
                raise HTTPException(422, "请选择有效草稿版本")
            turn.drafts = [drafts[choice - 1]] if choice is not None else drafts
            turn.intent.draft_requested = choice is not None
            return True
    return False


def start_turn(db, user_id, conversation_id, question, request_id=None, confirmation_id=None, selection=None, replace_id=None) -> Turn:
    now = datetime.now(timezone.utc)
    request_id = request_id or uuid.uuid4()
    request_hash = hashlib.sha256(json.dumps([str(conversation_id), question, str(confirmation_id), selection, str(replace_id)], ensure_ascii=False).encode()).hexdigest()
    existing = db.scalar(select(AssistantOperation).where(AssistantOperation.user_id == user_id, AssistantOperation.request_id == request_id))
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "请求编号已用于另一项请求")
        if existing.status in REPLAYABLE and existing.receipt and existing.expires_at > now:
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
        parents = db.scalars(select(AssistantOperation).where(
            AssistantOperation.user_id == user_id, AssistantOperation.conversation_id == conversation_id,
            AssistantOperation.status.in_((*PENDING, "drafted")), AssistantOperation.expires_at > now,
            AssistantOperation.context_fingerprint == context,
        ).order_by(AssistantOperation.created_at.desc()).limit(2)).all()
        parent = parents[0] if len(parents) == 1 and replace_id is None and intent.reason not in {"未获得当前直接操作授权", "能力询问不是操作授权"} else None
        choice = draft_choice(question)
        if parent is not None:
            if parent.status == "awaiting_selection" and choice is not None:
                options = parent.proposal.get("alternatives") or _verified_drafts(parent.proposal)
                named = re.search(r"([A-Ea-e])版", question)
                if named:
                    matches = [i for i, option in enumerate(options, 1) if re.match(re.escape(named.group(1)) + r"(?:版|$|\W)", option.get("label", ""), re.I)]
                    if len(matches) != 1:
                        raise HTTPException(422, "版本名称不明确，请回复候选序号")
                    choice = matches[0]
                selection, confirmation_id = choice, parent.id
            elif parent.status == "awaiting_confirmation" and CONFIRM_TEXT.fullmatch(control_text(question).strip()):
                confirmation_id = parent.id
            elif _resume_input(turn, parent, question):
                turn.parent_id = parent.id
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
            alternatives = parent.proposal.get("alternatives", [])
            drafts = _verified_drafts(parent.proposal)
            if alternatives or drafts:
                options = alternatives or drafts
                if selection is None or not 1 <= selection <= len(options):
                    raise HTTPException(422, "请选择有效版本序号")
                if alternatives:
                    change = options[selection - 1]["change"]
                    note = owned_note(db, uuid.UUID(change["note_id"]), user_id)
                    if note.version != change["version"] or note.body_md != change["before"]["body_md"] or note.title != change["before"]["title"]:
                        raise HTTPException(409, "笔记已变化，请重新提出修改请求")
                    turn.changes, turn.confirmed = [change], True
                else:
                    chosen = options[selection - 1]
                    turn.intent.create_title = turn.intent.create_title or chosen["title"]
                    turn.intent.create_body = chosen["body_md"]
                    turn.intent.missing = []
            else:
                candidates = parent.proposal.get("candidates", [])
                if selection is None or not 1 <= selection <= len(candidates):
                    raise HTTPException(422, "请选择有效候选序号")
                turn.selected_id = candidates[selection - 1]["note_id"]
                note = owned_note(db, uuid.UUID(turn.selected_id), user_id)
                if note.version != candidates[selection - 1]["version"]:
                    raise HTTPException(409, "候选笔记已变化，请重新选择")
                turn.selected_version = note.version
        elif parent.status == "awaiting_confirmation":
            if selection is not None:
                raise HTTPException(422, "该操作需要确认差异")
            turn.changes = parent.proposal.get("changes", [])
            turn.confirmed = True
        else:
            raise HTTPException(422, "此任务需要补充内容，不能确认保存")
    # A new human turn consumes/cancels the pending grant; text history cannot restore it.
    if conversation_id is not None:
        db.execute(update(AssistantOperation).where(
            AssistantOperation.user_id == user_id, AssistantOperation.conversation_id == conversation_id,
            AssistantOperation.status.in_((*PENDING, "drafted"))
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
    if turn.alternatives or (turn.intent.action == "create" and len(turn.drafts) > 1 and not turn.changes):
        options = turn.alternatives or turn.drafts
        descriptions = []
        for index, option in enumerate(options, 1):
            label = option.get("label") or f"{index}版"
            if "change" in option:
                change = option["change"]
                body = change["changes"].get("body_md", change["changes"].get("title", ""))
                original = change["before"]["body_md"]
                if turn.intent.scope and turn.intent.scope.startswith("paragraph:"):
                    start, end = paragraph_range(original, int(turn.intent.scope.split(":")[1]))
                    suffix_size = len(original) - end
                    body = body[start:len(body) - suffix_size if suffix_size else len(body)]
                elif turn.intent.scope == "append":
                    body = body[len(original):]
                elif turn.intent.scope == "prepend":
                    body = body[:len(body) - len(original)] if original else body
            else:
                body = option["body_md"]
            descriptions.append(f"**{label}**\n\n{body}")
        result["answer"] = "请选择要保存的版本；选择前尚未保存。\n\n" + "\n\n".join(descriptions)
        result["citations"] = []
        result["pending_operation"] = {"operation_id": str(turn.id), "kind": "selection", "candidates": [
            {"index": i, "title": f"{d.get('label') or str(i) + '版'} · {d.get('title') or d['change']['title']}", "notebook": None}
            for i, d in enumerate(options, 1)]}
    elif turn.candidates and turn.selected_id is None:
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
        missing = turn.intent.missing or (["target_title"] if turn.intent.action == "update" and turn.selected_id is None else ["body_md"] if turn.intent.action == "create" and turn.intent.create_body is None else [])
        if missing:
            turn.intent.missing = missing
            result["answer"] = "请补充要修改的笔记标题。" if "target_title" in missing else "请提供要保存的正文，或说明需要生成的内容；本轮尚未保存。"
            result["pending_operation"] = {"operation_id": str(turn.id), "kind": "input", "action": turn.intent.action, "missing": missing}
        else:
            result["answer"] = "本轮尚未保存笔记，也未生成可提交的修改提议。请重新描述需要保存的内容或修改范围。"
    elif not turn.drafts:
        # A model promise never creates a server operation or a confirmation UI.
        if re.search(r"(?:我(?:现在|马上|这就)?(?:就)?(?:来|会|将)?|现在)(?:提交|创建|保存|写入)(?:这篇|笔记|创建|新建|文章|正文)", result["answer"]):
            result["answer"] = "本轮没有执行笔记写入。请明确要新建的内容或要修改的笔记。"
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
        row.status = {"selection": "awaiting_selection", "confirmation": "awaiting_confirmation", "input": "awaiting_input"}[result["pending_operation"]["kind"]]
        row.intent = turn.intent.json()
        row.proposal = {"candidates": turn.candidates, "changes": turn.changes, "drafts": turn.drafts, "alternatives": turn.alternatives}
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
    if row.status in PENDING or (turn.drafts and not turn.changes and not turn.alternatives):
        if row.status not in PENDING:
            row.status, row.proposal = "drafted", {"drafts": turn.drafts}
            row.intent = turn.intent.json()
            row.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        row.receipt = response
        row.context_fingerprint = fingerprint(db, turn.user_id, turn.conversation_id)
    else:
        row.status, row.proposal = "committed" if turn.changes else "completed", {}
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
    expired = db.execute(update(AssistantOperation).where(AssistantOperation.status.in_((*PENDING, "running", "drafted")), AssistantOperation.expires_at <= now)
                         .values(status="cancelled", proposal={}, intent={}, receipt=None)).rowcount
    removed = db.execute(delete(AssistantOperation).where(
        ((AssistantOperation.status.in_(("committed", "completed"))) & (AssistantOperation.expires_at <= now)) |
        ((AssistantOperation.status.in_(("failed", "cancelled"))) & (AssistantOperation.created_at < now - timedelta(days=30)))
    )).rowcount
    return (expired or 0) + (removed or 0)
