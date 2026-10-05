"""Account-owned notes, sessions, taxonomy, and versioned index jobs."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Index, Integer, LargeBinary, SmallInteger, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import AssistantMessageRole, AuditActor, ChunkSource, IndexJobStatus, ModelProvider, NoteIndexStatus


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class Account(Base):
    __tablename__ = "pkm_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "pkm_user_sessions"
    __table_args__ = (Index("ix_user_sessions_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Notebook(Base):
    __tablename__ = "pkm_notebooks"
    __table_args__ = (
        Index("uq_notebooks_active_user_name", "user_id", "name", unique=True, postgresql_where=text("deleted_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Tag(Base):
    __tablename__ = "pkm_tags"
    __table_args__ = (
        Index("uq_tags_active_user_name", "user_id", "name", unique=True, postgresql_where=text("deleted_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Note(Base):
    __tablename__ = "pkm_notes"
    __table_args__ = (
        Index("ix_notes_active_user_updated", "user_id", "updated_at", "id", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_notes_active_user_notebook_updated", "user_id", "notebook_id", "updated_at", "id", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_notes_archive_user_deleted", "user_id", "deleted_at", "id", postgresql_where=text("deleted_at IS NOT NULL")),
        Index("ix_notes_archive_deleted", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    notebook_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="markdown")
    source_url: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    index_status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=NoteIndexStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NoteTemplate(Base):
    __tablename__ = "pkm_note_templates"
    __table_args__ = (
        Index("uq_note_templates_user_name", "user_id", "name", unique=True),
        Index("ix_note_templates_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NoteFileVersion(Base):
    __tablename__ = "pkm_note_file_versions"
    __table_args__ = (UniqueConstraint("note_id", "version", name="uq_note_file_version"), Index("ix_note_file_user_note_version", "user_id", "note_id", "version"))

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(24), nullable=False, default="filesystem", server_default="filesystem")
    extraction_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    extraction_error: Mapped[str | None] = mapped_column(String(500))
    extraction_fingerprint: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FileUploadSession(Base):
    __tablename__ = "pkm_file_upload_sessions"
    __table_args__ = (
        UniqueConstraint("object_key", name="uq_file_upload_object_key"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_file_upload_user_idempotency"),
        Index("ix_file_upload_sessions_user_expiry", "user_id", "expires_at"),
        Index("ix_file_upload_sessions_status_expiry", "status", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    convert_legacy: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)
    object_key: Mapped[str] = mapped_column(String(80), nullable=False)
    multipart_id: Mapped[str] = mapped_column(Text, nullable=False)
    notebook_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="uploading", server_default="uploading")
    uploaded_parts: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    note_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    duplicate_note_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FileIngestJob(Base):
    __tablename__ = "pkm_file_ingest_jobs"
    __table_args__ = (
        UniqueConstraint("file_version_id", name="uq_file_ingest_version"),
        Index("ix_file_ingest_jobs_status_available", "status", "available_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    file_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(500))
    vision_results: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LinkDraft(Base):
    __tablename__ = "pkm_link_drafts"
    __table_args__ = (
        Index("ix_link_drafts_user_updated", "user_id", "updated_at"),
        Index("ix_link_drafts_fetch_queue", "fetch_status", "updated_at"),
        Index("uq_link_drafts_user_url", "user_id", "source_url", unique=True, postgresql_where=text("status <> 'published'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    snapshot_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fetch_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    fetch_error: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    notebook_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NoteTag(Base):
    __tablename__ = "pkm_note_tags"
    __table_args__ = (
        Index("ix_note_tags_user_tag_note", "user_id", "tag_id", "note_id"),
    )

    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NoteChunk(Base):
    __tablename__ = "pkm_note_chunks"
    __table_args__ = (
        UniqueConstraint("note_id", "note_version", "ordinal", name="uq_chunk_position"),
        Index("ix_chunks_user_note_version", "user_id", "note_id", "note_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    note_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=ChunkSource.BODY)
    location: Mapped[dict | None] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NoteTextBlock(Base):
    __tablename__ = "pkm_note_text_blocks"
    __table_args__ = (UniqueConstraint("note_id", "content_version", "ordinal", name="uq_text_block_position"), Index("ix_text_blocks_user_note_version", "user_id", "note_id", "content_version"))

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    locator: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class MarkdownImageReference(Base):
    __tablename__ = "pkm_markdown_image_references"
    __table_args__ = (
        Index("ix_markdown_image_refs_image", "user_id", "image_note_id"),
        Index("ix_markdown_image_refs_markdown", "user_id", "markdown_note_id"),
    )

    markdown_note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    start_offset: Mapped[int] = mapped_column(Integer, primary_key=True)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    image_note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    alt_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IndexJob(Base):
    __tablename__ = "pkm_index_jobs"
    __table_args__ = (
        Index("ix_jobs_status_created", "status", "created_at"),
        Index(
            "uq_jobs_active_note", "note_id", unique=True,
            postgresql_where=text("status IN (1, 2)"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=IndexJobStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NoteRevision(Base):
    __tablename__ = "pkm_note_revisions"
    __table_args__ = (
        UniqueConstraint("note_id", "version", name="uq_revision_note_version"),
        Index("ix_revisions_user_note_version", "user_id", "note_id", "version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    note_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    notebook_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    tag_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuditEvent(Base):
    """业务语义层审计：动作、对象、变更字段。

    新增的可观测列全部可空，旧调用方（以及历史数据）无需改动。
    `request_id` 由中间件注入的上下文自动填充，用于把一次 HTTP 请求、
    它的访问日志和它引发的所有业务变更串成一条链。
    """

    __tablename__ = "pkm_audit_events"
    __table_args__ = (
        Index("ix_audit_user_created", "user_id", "created_at"),
        Index("ix_audit_entity_created", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_request", "request_id"),
        Index("ix_audit_user_action_created", "user_id", "action", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=AuditActor.USER)
    action: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    entity_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entity_version: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    outcome: Mapped[int | None] = mapped_column(SmallInteger)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AccessLog(Base):
    """请求层日志：全量 HTTP 访问，包含未被业务接受的失败请求。

    由中间件使用独立 Session 写入，因此不受业务事务回滚影响——
    这正是「越权 404 / 版本冲突 409 / 登录失败」能够留痕的原因。
    不记录请求体、查询串与凭据。
    """

    __tablename__ = "pkm_access_logs"
    __table_args__ = (
        Index("ix_access_request", "request_id"),
        Index("ix_access_user_created", "user_id", "created_at"),
        Index("ix_access_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    status_code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DigestSettings(Base):
    __tablename__ = "pkm_digest_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    daily_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    daily_time: Mapped[str] = mapped_column(String(5), nullable=False, default="21:00")
    daily_next_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    weekly_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    weekly_weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=6)
    weekly_time: Mapped[str] = mapped_column(String(5), nullable=False, default="21:00")
    weekly_next_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DigestRun(Base):
    __tablename__ = "pkm_digest_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "slot_key", name="uq_digest_user_kind_slot"),
        Index("ix_digest_runs_status_scheduled", "status", "scheduled_at"),
        Index("ix_digest_runs_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    slot_key: Mapped[str] = mapped_column(String(16), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    note_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_refs: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NoteReminder(Base):
    __tablename__ = "pkm_note_reminders"
    __table_args__ = (
        Index("ix_note_reminders_user_status_due", "user_id", "status", "due_at"),
        Index("ix_note_reminders_user_note", "user_id", "note_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    note_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    text: Mapped[str] = mapped_column(String(200), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ModelConnection(Base):
    __tablename__ = "pkm_model_connections"
    __table_args__ = (
        Index("uq_model_connections_active_user", "user_id", unique=True, postgresql_where=text("deleted_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=ModelProvider.DEEPSEEK)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    credential_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    credential_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssistantConversation(Base):
    __tablename__ = "pkm_assistant_conversations"
    __table_args__ = (Index("ix_assistant_conversations_user_updated", "user_id", "updated_at", "id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="新对话")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    context_summary: Mapped[str | None] = mapped_column(Text)
    summary_through_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    summary_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssistantMessage(Base):
    __tablename__ = "pkm_assistant_messages"
    __table_args__ = (
        Index("ix_assistant_messages_user_conversation_created", "user_id", "conversation_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AssistantTrace(Base):
    __tablename__ = "pkm_assistant_traces"
    __table_args__ = (
        Index("ix_assistant_traces_started", "started_at", "id"),
        Index("ix_assistant_traces_entry_status_started", "entrypoint", "status", "started_at"),
        Index("ix_assistant_traces_conversation_message", "conversation_id", "assistant_message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    assistant_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    entrypoint: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running", server_default="running")
    error_type: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    steps: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
