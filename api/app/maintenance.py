"""Explicit physical cleanup for disposable accounts in acceptance scripts."""

import uuid

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import (
    Account, AssistantConversation, AssistantMessage, AuditEvent, IndexJob,
    Note, NoteChunk, NoteRevision, ModelConnection, Notebook, NoteTag, Tag, UserSession,
)


def purge_accounts(db: Session, account_ids: list[uuid.UUID]) -> None:
    if not account_ids:
        return
    for model in (
        AssistantMessage, AssistantConversation, NoteChunk, NoteTag, IndexJob, NoteRevision, AuditEvent,
        UserSession, ModelConnection, Note, Tag, Notebook, Account,
    ):
        column = model.id if model is Account else model.user_id
        db.execute(delete(model).where(column.in_(account_ids)))
