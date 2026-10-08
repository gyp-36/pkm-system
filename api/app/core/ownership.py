"""归属解析的唯一入口。

所有按用户读取/锁定用户所属实体的查询都必须经本模块。旧代码把同一类查询散落在
notes.py / taxonomy.py / reminders.py / upload_sessions.py / conversations.py /
assistant.py 各处（且 assistant.py 还重复了一份 current_note），新端点很容易漏掉
user_id 过滤。集中到一处后，"归属过滤"只有一个构造点，门禁（contract_check）也只需
断言本模块与被允许的例外。
"""

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.auth.auth import Db
from app.core.models import (
    AssistantConversation,
    AssistantMessage,
    FileUploadSession,
    Note,
    NoteReminder,
    Notebook,
    Tag,
)


def owned_note(db: Db, note_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False) -> Note:
    query = select(Note).where(Note.id == note_id, Note.user_id == user_id, Note.deleted_at.is_(None))
    if lock:
        query = query.with_for_update()
    note = db.scalar(query)
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return note


def owned_notebook(db: Db, notebook_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False) -> Notebook:
    query = select(Notebook).where(Notebook.id == notebook_id, Notebook.user_id == user_id, Notebook.deleted_at.is_(None))
    if lock:
        query = query.with_for_update()
    notebook = db.scalar(query)
    if notebook is None:
        raise HTTPException(status_code=404, detail="笔记本不存在")
    return notebook


def owned_tag(db: Db, tag_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False) -> Tag:
    query = select(Tag).where(Tag.id == tag_id, Tag.user_id == user_id, Tag.deleted_at.is_(None))
    if lock:
        query = query.with_for_update()
    tag = db.scalar(query)
    if tag is None:
        raise HTTPException(status_code=404, detail="标签不存在")
    return tag


def owned_reminder(db: Db, reminder_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False) -> NoteReminder:
    query = select(NoteReminder).where(NoteReminder.id == reminder_id, NoteReminder.user_id == user_id, NoteReminder.status != "cancelled")
    if lock:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise HTTPException(status_code=404, detail="提醒不存在")
    return row


def owned_conversation(db: Db, conversation_id: uuid.UUID, user_id: uuid.UUID) -> AssistantConversation:
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


def owned_message(db: Db, conversation_id: uuid.UUID, user_id: uuid.UUID, message_id: uuid.UUID) -> AssistantMessage:
    message = db.scalar(select(AssistantMessage).where(
        AssistantMessage.id == message_id,
        AssistantMessage.conversation_id == conversation_id,
        AssistantMessage.user_id == user_id,
    ))
    if message is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    return message


def owned_session(db: Db, user_id: uuid.UUID, upload_id: uuid.UUID, *, lock: bool = False) -> FileUploadSession:
    query = select(FileUploadSession).where(FileUploadSession.id == upload_id, FileUploadSession.user_id == user_id)
    if lock:
        query = query.with_for_update()
    session = db.scalar(query)
    if session is None:
        raise HTTPException(status_code=404, detail="上传会话不存在")
    if session.expires_at <= datetime.now(timezone.utc) and session.status not in {"completed", "duplicate", "cancelled"}:
        raise HTTPException(status_code=410, detail="上传会话已过期，请重新上传")
    return session
