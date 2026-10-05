"""Persistent account-scoped knowledge-grounded assistant conversations."""

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, delete, func, or_, select

from app.assistant.assistant import answer_question, stream_answer_question, summarize_conversation_context
from app.assistant.tracing import TraceRecorder
from app.prompts import load_prompt
from app.auth.auth import Db, UserId
from app.core.enums import AssistantMessageRole, AuditAction, AuditEntityType
from app.core.lifecycle import record_event
from app.core.models import AssistantConversation, AssistantMessage
from app.core.rate_limit import check_limit


router = APIRouter(prefix="/v1/assistant/conversations", tags=["assistant conversations"])
log = logging.getLogger(__name__)
MAX_HISTORY_MESSAGES = 8
MAX_HISTORY_MESSAGE_CHARS = 1600
SUMMARY_THRESHOLD_MESSAGES = 16
SUMMARY_REFRESH_MESSAGES = 8
SUMMARY_FALLBACK_MESSAGES = 16


class QuestionInput(BaseModel):
    question: str = Field(min_length=1)
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


def message_json(item: AssistantMessage) -> dict:
    return {
        "id": str(item.id),
        "role": AssistantMessageRole(item.role).name.lower(),
        "content": item.content,
        "created_at": item.created_at.isoformat(),
    }


def require_conversation(db: Db, conversation_id: uuid.UUID, user_id: uuid.UUID) -> AssistantConversation:
    conversation = db.scalar(
        select(AssistantConversation).where(
            AssistantConversation.id == conversation_id,
            AssistantConversation.user_id == user_id,
            AssistantConversation.deleted_at.is_(None),
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return conversation


def message_context(item: AssistantMessage) -> dict | None:
    content = item.content if isinstance(item.content, dict) else {}
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
                    f"- {source.get('title', '笔记')}：{source.get('quote', '')}"
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
        text = re.sub(r"\[S\d+\]", "[历史引用]", text)
    if not isinstance(text, str) or not text.strip():
        return None
    return {"role": role, "content": text[:MAX_HISTORY_MESSAGE_CHARS]}


def require_message(db: Db, conversation_id: uuid.UUID, user_id: uuid.UUID, message_id: uuid.UUID) -> AssistantMessage:
    message = db.scalar(select(AssistantMessage).where(
        AssistantMessage.id == message_id,
        AssistantMessage.conversation_id == conversation_id,
        AssistantMessage.user_id == user_id,
    ))
    if message is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    return message


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
        "content": load_prompt("conversation_summary_context.txt", summary=summary),
    }


def load_question_history(db: Db, conversation_id: uuid.UUID, user_id: uuid.UUID, replace_from_message_id: uuid.UUID | None = None) -> list[dict]:
    conversation = require_conversation(db, conversation_id, user_id)
    cutoff = None
    if replace_from_message_id is not None:
        target = require_message(db, conversation_id, user_id, replace_from_message_id)
        if target.role != AssistantMessageRole.USER:
            raise HTTPException(status_code=422, detail="只能从用户问题重新提问")
        cutoff = target
    query = (
        select(AssistantMessage)
        .where(
            AssistantMessage.user_id == user_id,
            AssistantMessage.conversation_id == conversation_id,
        )
        .order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc())
        .limit(MAX_HISTORY_MESSAGES)
    )
    if cutoff is not None:
        query = query.where(or_(
            AssistantMessage.created_at < cutoff.created_at,
            (AssistantMessage.created_at == cutoff.created_at) & (AssistantMessage.id < cutoff.id),
        ))
    recent_rows = list(reversed(db.scalars(query).all()))

    # Re-asking from an earlier message creates a new branch. Use only history before
    # that point; the old summary may describe messages that are about to be removed.
    if cutoff is not None:
        history = [context for item in recent_rows if (context := message_context(item)) is not None]
        db.rollback()
        return history

    total_messages = db.scalar(select(func.count(AssistantMessage.id)).where(
        AssistantMessage.user_id == user_id,
        AssistantMessage.conversation_id == conversation_id,
    )) or 0
    history = [context for item in recent_rows if (context := message_context(item)) is not None]

    if total_messages > SUMMARY_THRESHOLD_MESSAGES and len(recent_rows) == MAX_HISTORY_MESSAGES:
        summary = conversation.context_summary
        cursor_id = conversation.summary_through_message_id
        cursor = None
        if summary and cursor_id:
            cursor = db.scalar(select(AssistantMessage).where(
                AssistantMessage.id == cursor_id,
                AssistantMessage.user_id == user_id,
                AssistantMessage.conversation_id == conversation_id,
            ))
            if cursor is None:
                # A summary whose checkpoint was removed cannot be trusted.
                summary = None
                cursor_id = None
                conversation.context_summary = None
                conversation.summary_through_message_id = None
                conversation.summary_updated_at = None
                db.commit()

        oldest_recent = recent_rows[0]
        older_query = (
            select(AssistantMessage)
            .where(
                AssistantMessage.user_id == user_id,
                AssistantMessage.conversation_id == conversation_id,
                message_before(oldest_recent),
            )
            .order_by(AssistantMessage.created_at, AssistantMessage.id)
        )
        if cursor is not None:
            older_query = older_query.where(message_after(cursor))
        older_rows = db.scalars(older_query).all()
        should_summarize = bool(older_rows) and (
            not summary or len(older_rows) >= SUMMARY_REFRESH_MESSAGES
        )
        if should_summarize:
            source_messages = [
                context for item in older_rows
                if (context := message_context(item)) is not None
            ]
            compacted = summarize_conversation_context(summary, source_messages, db, user_id)
            if compacted is not None:
                summary = compacted
                cursor = older_rows[-1]
                conversation.context_summary = compacted or None
                conversation.summary_through_message_id = cursor.id if compacted else None
                conversation.summary_updated_at = datetime.now(timezone.utc) if compacted else None
                db.commit()
                # If the model decided there was nothing durable to retain, keep the
                # source messages in the raw context rather than dropping them.
                if compacted:
                    older_rows = []

        if summary:
            history = [summary_message(summary)] + [
                context for item in [*older_rows, *recent_rows]
                if (context := message_context(item)) is not None
            ]
        elif older_rows:
            # Summarization is best-effort. On first-compaction failure, retain a
            # bounded raw window; the full transcript remains available in storage.
            fallback = list(reversed(db.scalars(
                select(AssistantMessage)
                .where(
                    AssistantMessage.user_id == user_id,
                    AssistantMessage.conversation_id == conversation_id,
                )
                .order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc())
                .limit(SUMMARY_FALLBACK_MESSAGES)
            ).all()))
            history = [context for item in fallback if (context := message_context(item)) is not None]

    db.rollback()
    return history


def save_question_result(db: Db, conversation_id: uuid.UUID, user_id: uuid.UUID, question: str, result: dict, replace_from_message_id: uuid.UUID | None = None) -> dict:
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
        target = require_message(db, conversation_id, user_id, replace_from_message_id)
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
            "answer_source": result.get("answer_source", "knowledge_base"),
        },
        created_at=assistant_created_at,
    )
    conversation.updated_at = assistant_created_at
    db.add_all([user_message, assistant_message])
    db.flush()
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
    db.commit()
    db.refresh(conversation)
    db.refresh(user_message)
    db.refresh(assistant_message)
    return {
        **conversation_json(conversation),
        "messages": [message_json(user_message), message_json(assistant_message)],
    }


@router.get("")
def list_conversations(db: Db, user_id: UserId) -> dict:
    items = db.scalars(
        select(AssistantConversation)
        .where(AssistantConversation.user_id == user_id, AssistantConversation.deleted_at.is_(None))
        .order_by(AssistantConversation.updated_at.desc(), AssistantConversation.id.desc())
    ).all()
    return {"items": [conversation_json(item) for item in items]}


@router.post("", status_code=201)
def create_conversation(db: Db, user_id: UserId) -> dict:
    item = AssistantConversation(user_id=user_id, title="新对话")
    db.add(item)
    db.flush()
    record_event(db, user_id, AuditAction.CREATE, AuditEntityType.CONVERSATION, item.id)
    db.commit()
    db.refresh(item)
    return conversation_json(item)


@router.patch("/{conversation_id}")
def rename_conversation(conversation_id: uuid.UUID, body: ConversationTitleInput, db: Db, user_id: UserId) -> dict:
    conversation = require_conversation(db, conversation_id, user_id)
    conversation.title = body.title
    conversation.updated_at = datetime.now(timezone.utc)
    record_event(db, user_id, AuditAction.RENAME, AuditEntityType.CONVERSATION, conversation.id,
                 details={"changed": ["title"]})
    db.commit()
    db.refresh(conversation)
    return conversation_json(conversation)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: uuid.UUID, db: Db, user_id: UserId) -> None:
    conversation = require_conversation(db, conversation_id, user_id)
    conversation.deleted_at = datetime.now(timezone.utc)
    conversation.updated_at = conversation.deleted_at
    record_event(db, user_id, AuditAction.DELETE, AuditEntityType.CONVERSATION, conversation.id)
    db.commit()


@router.get("/{conversation_id}")
def get_conversation(conversation_id: uuid.UUID, db: Db, user_id: UserId) -> dict:
    conversation = require_conversation(db, conversation_id, user_id)
    messages = db.scalars(
        select(AssistantMessage)
        .where(
            AssistantMessage.user_id == user_id,
            AssistantMessage.conversation_id == conversation.id,
        )
        .order_by(AssistantMessage.created_at, AssistantMessage.id)
    ).all()
    return {**conversation_json(conversation), "messages": [message_json(item) for item in messages]}


@router.delete("/{conversation_id}/messages/{message_id}")
def delete_message_and_following(conversation_id: uuid.UUID, message_id: uuid.UUID, db: Db, user_id: UserId) -> dict:
    conversation = db.scalar(select(AssistantConversation).where(
        AssistantConversation.id == conversation_id,
        AssistantConversation.user_id == user_id,
        AssistantConversation.deleted_at.is_(None),
    ).with_for_update())
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    target = require_message(db, conversation_id, user_id, message_id)
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
    messages = db.scalars(select(AssistantMessage).where(
        AssistantMessage.user_id == user_id,
        AssistantMessage.conversation_id == conversation_id,
    ).order_by(AssistantMessage.created_at, AssistantMessage.id)).all()
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


@router.post("/{conversation_id}/messages", status_code=201)
def send_question(conversation_id: uuid.UUID, body: QuestionInput, db: Db, user_id: UserId) -> dict:
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="问题不能为空")

    require_conversation(db, conversation_id, user_id)

    check_limit(user_id, "assistant", limit=10)
    history = load_question_history(db, conversation_id, user_id, body.replace_from_message_id)

    # 获取对话锁之前，先生成基于知识库内容的回答。
    # 如果生成失败（包括模型未配置），对话内容保持不变。
    trace = TraceRecorder("conversation", user_id, None, conversation_id)
    status, error_type = "success", None
    try:
        result = answer_question(question, db, user_id, history, limit_checked=True, trace=trace)
        saved = save_question_result(db, conversation_id, user_id, question, result, body.replace_from_message_id)
        trace.set_assistant_message(saved["messages"][1]["id"])
        return saved
    except Exception as exc:
        status, error_type = "error", type(exc).__name__
        raise
    finally:
        trace.finish(status, error_type)


@router.post("/{conversation_id}/messages/stream")
def stream_question(conversation_id: uuid.UUID, body: QuestionInput, db: Db, user_id: UserId):
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="问题不能为空")
    require_conversation(db, conversation_id, user_id)
    def event_stream():
        def event(payload: dict) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"

        yield event({"type": "status", "text": "正在理解问题并准备回答…"})
        trace = None
        trace_status, trace_error = "error", None
        try:
            check_limit(user_id, "assistant", limit=10)
            history = load_question_history(db, conversation_id, user_id, body.replace_from_message_id)
            trace = TraceRecorder("conversation_stream", user_id, None, conversation_id)
            answer_stream = stream_answer_question(question, db, user_id, history, limit_checked=True, trace=trace)
            while True:
                try:
                    payload = next(answer_stream)
                except StopIteration as finished:
                    result = finished.value
                    break
                yield event(payload)
            saved = save_question_result(db, conversation_id, user_id, question, result, body.replace_from_message_id)
            trace.set_assistant_message(saved["messages"][1]["id"])
            trace_status = "success"
            trace.finish(trace_status)
            yield event({"type": "complete", "result": saved})
        except HTTPException as exc:
            trace_error = type(exc).__name__
            if trace is not None:
                trace.finish(trace_status, trace_error)
            yield event({"type": "error", "detail": str(exc.detail)})
        except Exception as exc:
            trace_error = type(exc).__name__
            if trace is not None:
                trace.finish(trace_status, trace_error)
            log.warning("assistant conversation stream failed: %s", type(exc).__name__)
            yield event({"type": "error", "detail": "回答生成失败，请稍后重试"})
        finally:
            if trace is not None and trace_status != "success" and trace_error is None:
                trace.finish("cancelled", "GeneratorExit")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
