"""提醒与工作台的响应契约。"""

from app.contracts.base import ContractModel
from app.contracts.archive import ArchivedNoteOut
from app.contracts.notes import NoteOut


class ReminderOut(ContractModel):
    id: str
    note_id: str | None
    note_title: str | None
    text: str
    due_at: str
    status: str
    created_at: str
    updated_at: str


class ReminderListOut(ContractModel):
    items: list[ReminderOut]
    next_offset: int | None


class WorkbenchReportOut(ContractModel):
    id: str
    kind: str
    status: str
    note_id: str | None
    title: str
    excerpt: str
    topics: list[str]
    note_active: bool
    note_archived: bool
    period_start: str
    period_end: str
    scheduled_at: str
    updated_at: str


class WorkbenchOut(ContractModel):
    items: list[dict]
    reminders: list[ReminderOut]
    latest_daily: WorkbenchReportOut | None
    latest_weekly: WorkbenchReportOut | None
    archive: list[ArchivedNoteOut]
    recent_note: NoteOut | None
