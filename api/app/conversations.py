"""Persistent account-scoped assistant conversations for retrieval-only chat."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app.auth import Db, UserId
from app.enums import AssistantMessageRole
from app.models import AssistantConversation, AssistantMessage
from app.search import search_notes


router = APIRouter(prefix="/v1/assistant/conversations", tags=["assistant conversations"])


class QuestionInput(BaseModel):
    question: str = Field(min_length=1)


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
    db.commit()
    db.refresh(item)
    return conversation_json(item)


@router.patch("/{conversation_id}")
def rename_conversation(conversation_id: uuid.UUID, body: ConversationTitleInput, db: Db, user_id: UserId) -> dict:
    conversation = require_conversation(db, conversation_id, user_id)
    conversation.title = body.title
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conversation)
    return conversation_json(conversation)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: uuid.UUID, db: Db, user_id: UserId) -> None:
    conversation = require_conversation(db, conversation_id, user_id)
    conversation.deleted_at = datetime.now(timezone.utc)
    conversation.updated_at = conversation.deleted_at
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


@router.post("/{conversation_id}/messages", status_code=201)
def send_question(conversation_id: uuid.UUID, body: QuestionInput, db: Db, user_id: UserId) -> dict:
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="问题不能为空")

    require_conversation(db, conversation_id, user_id)

    # Run retrieval before acquiring the conversation lock; the user and assistant
    # records themselves are committed together below.
    result = search_notes(db, user_id, question, mode="hybrid", limit=10)

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
        content={"items": result["items"], "semantic_status": result["semantic_status"]},
        created_at=assistant_created_at,
    )
    conversation.updated_at = assistant_created_at
    db.add_all([user_message, assistant_message])
    db.commit()
    db.refresh(conversation)
    db.refresh(user_message)
    db.refresh(assistant_message)
    return {
        **conversation_json(conversation),
        "messages": [message_json(user_message), message_json(assistant_message)],
    }
