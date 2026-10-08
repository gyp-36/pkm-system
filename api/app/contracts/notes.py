"""笔记与笔记分块的响应契约（出站边界）。"""

from __future__ import annotations

from app.contracts.base import ContractModel


class FileMetaOut(ContractModel):
    filename: str
    extension: str
    media_type: str
    size_bytes: int
    file_version: int
    sha256: str
    # 仅 note_payload（上传路径）会带这三项；note_json 路径缺省为 None。
    extraction_status: str | None = None
    extraction_error: str | None = None
    extraction_fingerprint: str | None = None


class OriginalFileOut(ContractModel):
    filename: str
    extension: str
    file_version: int


class NoteOut(ContractModel):
    id: str
    title: str
    excerpt: str
    notebook_id: str | None
    tag_ids: list[str]
    version: int
    index_status: str
    created_at: str
    updated_at: str
    content_kind: str
    source_url: str | None
    file: FileMetaOut | None = None
    original_files: list[OriginalFileOut] | None = None
    extraction_status: str | None = None
    body_md: str | None = None
    digest_sources_changed: int | None = None


class NoteListOut(ContractModel):
    items: list[NoteOut]
    next_cursor: str | None


class NoteChunkOut(ContractModel):
    ordinal: int
    source: str
    start_offset: int
    end_offset: int
    content: str
    location: dict | None
    embedding: dict | None


class NoteChunksOut(ContractModel):
    note_id: str
    title: str
    content_version: int
    index_status: str
    total_chunks: int
    chunks: list[NoteChunkOut]


class ImageReferenceOut(ContractModel):
    note_id: str
    title: str
    references: int


class ImageReferenceListOut(ContractModel):
    items: list[ImageReferenceOut]
    total_notes: int
    total_references: int
