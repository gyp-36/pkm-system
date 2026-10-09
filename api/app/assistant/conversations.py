"""Persistent account-scoped knowledge-grounded assistant conversations."""

import json
import logging
import re
import uuid
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, delete, func, or_, select

from app.assistant.assistant import answer_question, stream_answer_question, summarize_conversation_context, answer_system_prompt
from app.assistant.tracing import TraceRecorder
from app.assistant.policy import MAX_QUESTION_CHARS, MAX_CONTEXT_BYTES
from app.assistant import conversation_memory as memory
from app.assistant.operations import start_turn, prepare_result, apply_changes, finish_turn, fail_turn, fingerprint
from app.assistant.projections import public_content, public_conversation
from app.assistant.visibility import project_text
from app.prompts import load_prompt
from app.auth.auth import Db, UserId
from app.core.enums import AssistantMessageRole, AuditAction, AuditEntityType
from app.core.lifecycle import record_event
from app.core.models import AssistantConversation, AssistantMessage, Note
from app.core.db import SessionLocal
from app.core.ownership import owned_conversation, owned_message
from app.contracts.conversations import (ConversationListOut, ConversationOut, ConversationWithMessagesOut)
from app.core.rate_limit import check_limit


router = APIRouter(prefix="/v1/assistant/conversations", tags=["assistant conversations"])
log = logging.getLogger(__name__)
MAX_HISTORY_MESSAGES = 8


class QuestionInput(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    request_id: uuid.UUID | None = None
    confirmation_id: uuid.UUID | None = None
    selection: int | None = Field(default=None, ge=1, le=20)
    replace_from_message_id: uuid.UUID | None = None


class ConversationTitleInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("标题不能为空")
        return value


def conversation_json(item: AssistantConversation) -> dict:
    return {
        "id": str(item.id),
        "title": item.title,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def stored_literals(item: AssistantMessage) -> list[str]:
    """Revalidate server provenance; arbitrary legacy extension fields aren't grants."""
    sources = item.content.get("_literal_sources", []) if isinstance(item.content, dict) else []
    result = []
    if not isinstance(sources, list) or not sources:
        return result
    with SessionLocal() as db:
        for source in sources[:20]:
            if not isinstance(source, dict):
                continue
            try:
                note = db.scalar(select(Note).where(Note.id == uuid.UUID(source["note_id"]), Note.user_id == item.user_id, Note.deleted_at.is_(None)))
                if note is None or note.version != source["note_version"] or source["source_field"] not in {"title", "body"}:
                    continue
                text = note.title if source["source_field"] == "title" else note.body_md
                start, end = source["start_offset"], source["end_offset"]
                if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(text):
                    continue
                literal = text[start:end]
                if hashlib.sha256(literal.encode()).hexdigest() == source["digest"]:
                    result.append(literal)
            except (KeyError, ValueError, TypeError):
                continue
    return result


def scope_source_cards(content: dict, user_id: uuid.UUID) -> dict:
    """Stored pointers require ownership too; shape validation is not a grant."""
    cards = content.get("citations", [])
    if not cards:
        return content
    owned = []
    with SessionLocal() as db:
        for card in cards:
            try:
                note = db.scalar(select(Note).where(
                    Note.id == uuid.UUID(card["note_id"]),
                    Note.user_id == user_id,
                    Note.deleted_at.is_(None),
                ))
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
            if note is not None:
                owned.append({**card, "title": note.title})
    if len(owned) == len(cards):
        return {**content, "citations": owned}
    return {**content, "citations": owned, "answer_source": "unknown"}


def message_json(item: AssistantMessage, *, literals=()) -> dict:
    return {
        "id": str(item.id),
        "role": AssistantMessageRole(item.role).name.lower(),
        "content": scope_source_cards(public_content(item.content, user=item.role == AssistantMessageRole.USER, literals=[*literals, *stored_literals(item)]), item.user_id),
        "created_at": item.created_at.isoformat(),
    }


def message_context(item: AssistantMessage) -> dict | None:
    literals = stored_literals(item) if getattr(item, "user_id", None) is not None else []
    content = public_content(item.content, user=item.role == AssistantMessageRole.USER, literals=literals)
    content = scope_source_cards(content, getattr(item, "user_id", None))
    if item.role == AssistantMessageRole.USER:
        role, text = "user", content.get("text", "")
    else:
        role = "assistant"
        if isinstance(content.get("answer"), str):
            text = content["answer"]
            source_mode = content.get("answer_source")
            if source_mode in {"mixed", "model_knowledge"}:
                text += "\n此前回答可能包含通用知识；这段历史只用于理解上下文，不会单独触发个人笔记检索。"
            citations = content.get("citations", [])
            if isinstance(citations, list) and citations:
                sources = [
                    f"- {source.get('title', '笔记')}"
                    for source in citations
                    if isinstance(source, dict)
                ]
                if sources:
                    text += "\n此前引用（仅用于理解上下文；只有当前问题明确要求依据相关笔记时才重新检索）：\n" + "\n".join(sources)
        else:
            # 旧版仅检索的助手消息仍可用作对话上下文。
            hits = content.get("items", [])
            snippets = [
                f"- {hit.get('title', '笔记')}：{hit.get('snippet', '')}"
                for hit in hits
                if isinstance(hit, dict)
            ] if isinstance(hits, list) else []
            text = "此前检索结果（仅用于理解上下文；只有当前问题明确要求依据相关笔记时才重新检索）：\n" + "\n".join(snippets)
    if role == "assistant" and isinstance(text, str):
        text = project_text(re.sub(r"\[S\d+\]", "[历史引用]", text), literals=literals)
    if not isinstance(text, str) or not text.strip():
        return None
    return {"role": role, "content": text}


def from_message_onward(message: AssistantMessage):
    return or_(
        AssistantMessage.created_at > message.created_at,
        (AssistantMessage.created_at == message.created_at) & (AssistantMessage.id >= message.id),
    )


def message_before(boundary: AssistantMessage):
    return or_(
        AssistantMessage.created_at < boundary.created_at,
        and_(AssistantMessage.created_at == boundary.created_at, AssistantMessage.id < boundary.id),
    )


def message_after(boundary: AssistantMessage):
    return or_(
        AssistantMessage.created_at > boundary.created_at,
        and_(AssistantMessage.created_at == boundary.created_at, AssistantMessage.id > boundary.id),
    )


def summary_message(summary: str) -> dict:
    return {
        "role": "assistant",
        "content": load_prompt("conversation_summary_context.txt", summary=project_text(summary)),
    }


def load_question_history(db: Db, conversation_id: uuid.UUID, user_id: uuid.UUID,
                          replace_from_message_id: uuid.UUID | None = None, *, question: str = "", trace=None) -> list[dict]:
    conversation = owned_conversation(db, conversation_id, user_id)
    query = select(AssistantMessage).where(
        AssistantMessage.user_id == user_id, AssistantMessage.conversation_id == conversation_id,
    ).order_by(AssistantMessage.created_at, AssistantMessage.id)
    if replace_from_message_id is not None:
        target = owned_message(db, conversation_id, user_id, replace_from_message_id)
        if target.role != AssistantMessageRole.USER:
            raise HTTPException(422, "只能从用户问题重新提问")
        query = query.where(message_before(target))
    rows = list(db.scalars(query).all())
    contexts = [message_context(row) for row in rows]
    state = memory.load_state(db, conversation, rows)
    # Model calls roll back the read transaction. Keep an immutable source
    # snapshot rather than expired ORM objects that could reload a newer branch.
    rows = [SimpleNamespace(id=row.id, role=row.role, content=dict(row.content), created_at=row.created_at) for row in rows]
    snapshot_hash = memory.transcript_hash(rows)
    reserve = 24_000 if memory.FOLLOWUP.search(question) or re.search(r"原文|全文|完整内容|方案|版本", question) else 12_000
    budget = min(memory.HISTORY_BYTES, MAX_CONTEXT_BYTES - memory.encoded_size(answer_system_prompt())
                 - memory.encoded_size(question) - reserve)
    if budget < 2000:
        raise HTTPException(422, "当前问题占用过多上下文预算，请分段处理；原始会话仍完整保留。")
    summary, covered, status = None, 0, "not_needed"
    metadata = conversation.summary_metadata or {}
    # A legacy summary without a source fingerprint is rebuilt from original
    # messages; a replacement branch never reuses future summaries.
    if replace_from_message_id is None and conversation.context_summary and metadata.get("schema_version") == memory.SCHEMA_VERSION:
        covered = metadata.get("covered_messages", 0)
        if (type(covered) is int and 0 < covered <= len(rows)
                and metadata.get("source_hash") == memory.transcript_hash(rows[:covered])
                and conversation.summary_through_message_id == rows[covered - 1].id):
            summary = conversation.context_summary
            status = "reused"
        else:
            covered = 0
    raw_size = memory.encoded_size([c for c in contexts if c is not None])
    remaining_size = memory.encoded_size([c for c in contexts[covered:] if c is not None])
    frame_size = memory.encoded_size(memory.memory_frame(state, memory.make_registry(rows, contexts), question)) if rows else 0
    needs_compaction = raw_size > budget and (not summary or remaining_size + frame_size + memory.encoded_size(summary) > budget - 1000)
    if needs_compaction:
        boundary = memory.recent_boundary(rows)
        if boundary > covered:
            source_messages = contexts[covered:boundary]
            candidate = summary
            status = "failed"
            batches = list(memory.summary_batches(source_messages))
            # A large uncompressed legacy transcript may require many requests.
            # Never advance the coverage checkpoint for a partially processed batch.
            if len(batches) <= 4:
                for batch in batches:
                    try:
                        compacted = summarize_conversation_context(candidate, batch, db, user_id)
                    except Exception as exc:
                        log.warning("conversation memory compaction failed: %s", type(exc).__name__)
                        compacted = None
                    if not compacted:
                        break
                    candidate = compacted
                else:
                    if candidate:
                        summary, covered, status = candidate, boundary, "updated"
            else:
                status = "deferred_large_transcript"
            if status == "updated" and replace_from_message_id is None:
                # Model calls release the DB transaction. Compare the whole source
                # snapshot while holding the conversation lock before publishing.
                locked = db.scalar(select(AssistantConversation).where(
                    AssistantConversation.id == conversation_id, AssistantConversation.user_id == user_id,
                    AssistantConversation.deleted_at.is_(None)).with_for_update())
                current = list(db.scalars(select(AssistantMessage).where(
                    AssistantMessage.conversation_id == conversation_id, AssistantMessage.user_id == user_id,
                ).order_by(AssistantMessage.created_at, AssistantMessage.id)).all())
                if locked is None or memory.transcript_hash(current) != snapshot_hash:
                    db.rollback()
                    raise HTTPException(409, "对话上下文已经变化，请基于最新消息重新提问")
                locked.context_summary = summary
                locked.summary_through_message_id = rows[covered - 1].id
                locked.summary_updated_at = datetime.now(timezone.utc)
                locked.summary_metadata = {"schema_version": memory.SCHEMA_VERSION,
                    "covered_messages": covered, "source_hash": memory.transcript_hash(rows[:covered])}
                db.commit()
    history = memory.assemble(rows, contexts, state, question=question, summary=summary,
                              covered=covered, budget=budget, summary_status=status)
    if trace is not None:
        trace.add_step("context", "会话上下文装配", summary=history.manifest)
    db.rollback()
    return history


def save_question_result(db: Db, conversation_id: uuid.UUID, user_id: uuid.UUID, question: str, result: dict, replace_from_message_id: uuid.UUID | None = None, *, commit: bool = True) -> dict:
    conversation = db.scalar(
        select(AssistantConversation)
        .where(
            AssistantConversation.id == conversation_id,
            AssistantConversation.user_id == user_id,
            AssistantConversation.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if conversation is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="对话不存在")

    if replace_from_message_id is not None:
        target = owned_message(db, conversation_id, user_id, replace_from_message_id)
        if target.role != AssistantMessageRole.USER:
            db.rollback()
            raise HTTPException(status_code=422, detail="只能从用户问题重新提问")
        db.execute(delete(AssistantMessage).where(
            AssistantMessage.user_id == user_id,
            AssistantMessage.conversation_id == conversation_id,
            from_message_onward(target),
        ))
        conversation.context_summary = None
        conversation.summary_through_message_id = None
        conversation.summary_updated_at = None
        conversation.summary_metadata = None

    first_user_message = db.scalar(
        select(AssistantMessage.id)
        .where(
            AssistantMessage.user_id == user_id,
            AssistantMessage.conversation_id == conversation.id,
            AssistantMessage.role == AssistantMessageRole.USER,
        )
        .limit(1)
    ) is None
    if first_user_message:
        conversation.title = question[:18]

    latest_created_at = db.scalar(
        select(AssistantMessage.created_at)
        .where(
            AssistantMessage.user_id == user_id,
            AssistantMessage.conversation_id == conversation.id,
        )
        .order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc())
        .limit(1)
    )
    user_created_at = datetime.now(timezone.utc)
    if latest_created_at is not None and latest_created_at >= user_created_at:
        user_created_at = latest_created_at + timedelta(microseconds=1)
    assistant_created_at = user_created_at + timedelta(microseconds=1)

    user_message = AssistantMessage(
        user_id=user_id,
        conversation_id=conversation.id,
        role=AssistantMessageRole.USER,
        content={"text": question},
        created_at=user_created_at,
    )
    assistant_message = AssistantMessage(
        user_id=user_id,
        conversation_id=conversation.id,
        role=AssistantMessageRole.ASSISTANT,
        content={
            "answer": result["answer"],
            "citations": result["citations"],
            "semantic_status": result["semantic_status"],
            "answer_source": result.get("answer_source", "unknown"),
            "retrieval_status": result.get("retrieval_status", "unknown"),
            "pending_operation": result.get("pending_operation"),
            "operation_receipts": result.get("operation_receipts", []),
            "_literal_sources": result.get("_literal_sources", []),
            "_finish_reason": result.get("_finish_reason"),
        },
        created_at=assistant_created_at,
    )
    conversation.updated_at = assistant_created_at
    db.add_all([user_message, assistant_message])
    db.flush()
    memory_rows = list(db.scalars(select(AssistantMessage).where(
        AssistantMessage.conversation_id == conversation.id, AssistantMessage.user_id == user_id,
    ).order_by(AssistantMessage.created_at, AssistantMessage.id)).all())
    memory.sync_memory(db, conversation, memory_rows)
    # 只记提问长度与是否重问，不落问题原文。
    record_event(
        db, user_id, AuditAction.CREATE, AuditEntityType.ASSISTANT_MESSAGE, user_message.id,
        details={
            "conversation_id": str(conversation.id),
            "question_chars": len(question),
            "replaced_from": str(replace_from_message_id) if replace_from_message_id else None,
            "answer_source": result.get("answer_source", "knowledge_base"),
        },
    )
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(conversation)
    db.refresh(user_message)
    db.refresh(assistant_message)
    return {
        **conversation_json(conversation),
        "messages": [message_json(user_message), message_json(assistant_message, literals=[question])],
    }


@router.get("", response_model=ConversationListOut)
def list_conversations(db: Db, user_id: UserId) -> dict:
    items = db.scalars(
        select(AssistantConversation)
        .where(AssistantConversation.user_id == user_id, AssistantConversation.deleted_at.is_(None))
        .order_by(AssistantConversation.updated_at.desc(), AssistantConversation.id.desc())
    ).all()
    return {"items": [conversation_json(item) for item in items]}


@router.post("", status_code=201, response_model=ConversationOut)
def create_conversation(db: Db, user_id: UserId) -> dict:
    item = AssistantConversation(user_id=user_id, title="新对话")
    db.add(item)
    db.flush()
    record_event(db, user_id, AuditAction.CREATE, AuditEntityType.CONVERSATION, item.id)
    db.commit()
    db.refresh(item)
    return conversation_json(item)


@router.patch("/{conversation_id}", response_model=ConversationOut)
def rename_conversation(conversation_id: uuid.UUID, body: ConversationTitleInput, db: Db, user_id: UserId) -> dict:
    conversation = owned_conversation(db, conversation_id, user_id)
    conversation.title = body.title
    conversation.updated_at = datetime.now(timezone.utc)
    record_event(db, user_id, AuditAction.RENAME, AuditEntityType.CONVERSATION, conversation.id,
                 details={"changed": ["title"]})
    db.commit()
    db.refresh(conversation)
    return conversation_json(conversation)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: uuid.UUID, db: Db, user_id: UserId) -> None:
    conversation = owned_conversation(db, conversation_id, user_id)
    conversation.deleted_at = datetime.now(timezone.utc)
    conversation.updated_at = conversation.deleted_at
    memory.clear_memory(db, conversation)
    record_event(db, user_id, AuditAction.DELETE, AuditEntityType.CONVERSATION, conversation.id)
    db.commit()


@router.get("/{conversation_id}", response_model=ConversationWithMessagesOut)
def get_conversation(conversation_id: uuid.UUID, db: Db, user_id: UserId) -> dict:
    conversation = owned_conversation(db, conversation_id, user_id)
    messages = db.scalars(
        select(AssistantMessage)
        .where(
            AssistantMessage.user_id == user_id,
            AssistantMessage.conversation_id == conversation.id,
        )
        .order_by(AssistantMessage.created_at, AssistantMessage.id)
    ).all()
    literals = []
    projected = []
    for item in messages:
        if item.role == AssistantMessageRole.USER and isinstance(item.content, dict) and isinstance(item.content.get("text"), str):
            literals.append(item.content["text"])
        projected.append(message_json(item, literals=literals))
    return {**conversation_json(conversation), "messages": projected}


@router.delete("/{conversation_id}/messages/{message_id}", response_model=ConversationWithMessagesOut)
def delete_message_and_following(conversation_id: uuid.UUID, message_id: uuid.UUID, db: Db, user_id: UserId) -> dict:
    conversation = db.scalar(select(AssistantConversation).where(
        AssistantConversation.id == conversation_id,
        AssistantConversation.user_id == user_id,
        AssistantConversation.deleted_at.is_(None),
    ).with_for_update())
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    target = owned_message(db, conversation_id, user_id, message_id)
    removed_count = db.scalar(
        select(func.count())
        .select_from(AssistantMessage)
        .where(
            AssistantMessage.user_id == user_id,
            AssistantMessage.conversation_id == conversation_id,
            from_message_onward(target),
        )
    )
    db.execute(delete(AssistantMessage).where(
        AssistantMessage.user_id == user_id,
        AssistantMessage.conversation_id == conversation_id,
        from_message_onward(target),
    ))
    conversation.context_summary = None
    conversation.summary_through_message_id = None
    conversation.summary_updated_at = None
    conversation.summary_metadata = None
    messages = db.scalars(select(AssistantMessage).where(
        AssistantMessage.user_id == user_id,
        AssistantMessage.conversation_id == conversation_id,
    ).order_by(AssistantMessage.created_at, AssistantMessage.id)).all()
    memory.sync_memory(db, conversation, list(messages))
    if not messages:
        conversation.title = "新对话"
    conversation.updated_at = datetime.now(timezone.utc)
    record_event(
        db, user_id, AuditAction.DELETE, AuditEntityType.ASSISTANT_MESSAGE, target.id,
        details={"conversation_id": str(conversation_id), "deleted_count": int(removed_count or 0)},
    )
    db.commit()
    db.refresh(conversation)
    return {**conversation_json(conversation), "messages": [message_json(item) for item in messages]}


def execute_question(conversation_id: uuid.UUID, body: QuestionInput, db: Db, user_id: uuid.UUID) -> dict:
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "问题不能为空")
    owned_conversation(db, conversation_id, user_id)
    turn = start_turn(db, user_id, conversation_id, question, body.request_id, body.confirmation_id, body.selection, body.replace_from_message_id)
    if turn.replay is not None:
        literals = []
        for message in turn.replay.get("messages", []):
            try:
                stored = db.scalar(select(AssistantMessage).where(AssistantMessage.id == uuid.UUID(message["id"]), AssistantMessage.user_id == user_id, AssistantMessage.conversation_id == conversation_id))
                if stored is not None:
                    literals.extend(stored_literals(stored))
            except (KeyError, ValueError, TypeError):
                continue
        replay = public_conversation(turn.replay, literals=literals)
        for message in replay["messages"]:
            message["content"] = scope_source_cards(message["content"], user_id)
        return replay
    trace = TraceRecorder("conversation", user_id, None, conversation_id)
    try:
        check_limit(user_id, "assistant", limit=10)
        history = load_question_history(db, conversation_id, user_id, body.replace_from_message_id, question=question, trace=trace)
        # A selected target is a server fact, never an authority assertion in model history.
        if turn.selected_id and not turn.confirmed:
            history = [*history, {"role": "user", "content": "本轮继续执行：" + turn.intent.target_title + "；请按该名称定位并读取。"}]
        raw = {"answer": "确认差异", "citations": [], "semantic_status": "not_requested", "answer_source": "model_knowledge", "retrieval_status": "not_requested"} if turn.confirmed else answer_question(question, db, user_id, history, limit_checked=True, trace=trace, turn=turn)
        result = prepare_result(turn, raw)
        # Lock conversation first, then grants/notes in one short transaction.
        conversation = db.scalar(select(AssistantConversation).where(
            AssistantConversation.id == conversation_id, AssistantConversation.user_id == user_id,
            AssistantConversation.deleted_at.is_(None)
        ).with_for_update())
        if conversation is None:
            raise HTTPException(404, "对话不存在")
        apply_changes(db, turn, result)
        saved = save_question_result(db, conversation_id, user_id, question, result, body.replace_from_message_id, commit=False)
        finish_turn(db, turn, saved)
        trace.set_assistant_message(saved["messages"][1]["id"])
        trace.finish("success")
        return saved
    except Exception as exc:
        fail_turn(db, turn)
        trace.finish("error", type(exc).__name__)
        raise


@router.post("/{conversation_id}/messages", status_code=201, response_model=ConversationWithMessagesOut)
def send_question(conversation_id: uuid.UUID, body: QuestionInput, db: Db, user_id: UserId) -> dict:
    return execute_question(conversation_id, body, db, user_id)


@router.post("/{conversation_id}/messages/stream")
def stream_question(conversation_id: uuid.UUID, body: QuestionInput, db: Db, user_id: UserId):
    if not body.question.strip():
        raise HTTPException(422, "问题不能为空")
    owned_conversation(db, conversation_id, user_id)

    def event_stream():
        def event(payload: dict) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
        yield event({"type": "status", "text": "正在准备并核验回答…"})
        try:
            saved = execute_question(conversation_id, body, db, user_id)
            answer = saved["messages"][1]["content"]["answer"]
            # Everything is validated and durable before the first answer byte leaves.
            for start in range(0, len(answer), 48):
                yield event({"type": "delta", "text": answer[start:start + 48]})
            yield event({"type": "complete", "result": saved})
        except HTTPException as exc:
            db.rollback()
            yield event({"type": "error", "detail": str(exc.detail)})
        except Exception as exc:
            db.rollback()
            log.warning("assistant stream failed: %s", type(exc).__name__)
            yield event({"type": "error", "detail": "回答生成失败，请稍后重试"})

    return StreamingResponse(event_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
