"""归档笔记响应契约（笔记投影 + 删除时间信息）。"""

from app.contracts.base import ContractModel
from app.contracts.notes import NoteOut


class ArchivedNoteOut(NoteOut):
    deleted_at: str
    purge_at: str
    days_remaining: int


class ArchiveListOut(ContractModel):
    items: list[ArchivedNoteOut]
    next_cursor: str | None


class ArchiveRestoreOut(ContractModel):
    id: str
    title: str


class PurgeFailureOut(ContractModel):
    id: str
    error: str


class ArchivePurgeOut(ContractModel):
    purged: list[str]
    failed: list[PurgeFailureOut]
