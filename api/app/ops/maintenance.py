"""Physical cleanup: disposable accounts and expired request access logs.

保留策略的分工：

- `purge_accounts` 在账号注销时清除该账号的全部个人数据，审计事件也在其中——
  注销意味着数据主体消失，留存其审计行不再有正当理由。
- `purge_access_logs` 按保留期清理**请求访问日志**。访问日志是取证素材，
  密度高、价值随时间衰减，需要定期回收磁盘。
- 业务审计（`pkm_audit_events`）**不设自动过期**：它是变更账本，行数增长慢，
  事后追责时需要长期可得，因此只随账号注销清除。
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import object_storage
from app.core.db import SessionLocal
from app.core.models import (
    AccessLog, Account, AssistantOperation, AssistantConversation, AssistantMessage, AssistantTrace, AssistantMemory, AssistantArtifact, AuditEvent, FileIngestJob,
    FileUploadSession, IndexJob, LinkDraft, MarkdownImageReference, Note, NoteChunk, NoteFileVersion,
    NoteRevision, NoteTextBlock, ModelConnection, Notebook, NoteTag, Tag, UserSession,
    DigestRun, DigestSettings, NoteReminder,
)
from app.knowledge.m3 import _file_path


ACCESS_LOG_RETENTION_ENV = "ACCESS_LOG_RETENTION_DAYS"
ACCESS_LOG_DEFAULT_RETENTION_DAYS = 90
ACCESS_LOG_BATCH_SIZE = 5000


def access_log_retention_days() -> int:
    raw = os.getenv(ACCESS_LOG_RETENTION_ENV, "").strip()
    if not raw:
        return ACCESS_LOG_DEFAULT_RETENTION_DAYS
    try:
        days = int(raw)
    except ValueError:
        return ACCESS_LOG_DEFAULT_RETENTION_DAYS
    # 下限 1 天：配成 0 或负数会连当天的取证素材一起删掉。
    return max(1, days)


def count_expired_access_logs(cutoff: datetime) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count()).select_from(AccessLog).where(AccessLog.created_at < cutoff)
        )


def purge_access_logs(
    *,
    days: int | None = None,
    batch_size: int = ACCESS_LOG_BATCH_SIZE,
    dry_run: bool = False,
) -> int:
    """删除 `created_at` 早于保留期的访问日志，返回删除行数。

    分批提交（单批一个事务），避免长事务持锁；中途失败也不会回滚已清理的部分。
    业务审计不受影响——这是与 `pkm_audit_events` 保留策略的关键区别。
    """
    keep_days = days if days is not None else access_log_retention_days()
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    if dry_run:
        return count_expired_access_logs(cutoff)

    removed = 0
    while True:
        with SessionLocal.begin() as db:
            batch = db.scalars(
                select(AccessLog.id)
                .where(AccessLog.created_at < cutoff)
                .order_by(AccessLog.created_at)
                .limit(max(1, batch_size))
            ).all()
            if not batch:
                break
            removed += db.execute(delete(AccessLog).where(AccessLog.id.in_(batch))).rowcount or 0
        if len(batch) < batch_size:
            break
    return removed


def purge_accounts(db: Session, account_ids: list[uuid.UUID]) -> None:
    if not account_ids:
        return
    versions = db.query(NoteFileVersion).filter(NoteFileVersion.user_id.in_(account_ids)).all()
    uploads = db.query(FileUploadSession).filter(FileUploadSession.user_id.in_(account_ids)).all()
    for row in versions:
        try:
            if row.storage_backend == "s3":
                object_storage.delete(row.storage_key)
            else:
                _file_path(row.storage_key).unlink(missing_ok=True)
        except Exception:
            pass
    for row in uploads:
        try:
            object_storage.abort_multipart(row.object_key, row.multipart_id)
        except Exception:
            pass
        try:
            object_storage.delete(row.object_key)
        except Exception:
            pass
    for model in (
        AssistantMemory, AssistantArtifact, AssistantOperation, AssistantTrace, AssistantMessage, AssistantConversation, FileIngestJob, NoteTextBlock,
        FileUploadSession, LinkDraft, MarkdownImageReference, NoteFileVersion, NoteChunk, NoteTag, IndexJob, NoteRevision, AuditEvent,
        AccessLog,
        NoteReminder, DigestRun, DigestSettings, UserSession, ModelConnection, Note, Tag, Notebook, Account,
    ):
        column = model.id if model is Account else model.user_id
        db.execute(delete(model).where(column.in_(account_ids)))
