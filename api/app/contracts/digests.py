"""日报/周报响应契约。"""

from app.contracts.base import ContractModel


class DigestSettingsOut(ContractModel):
    daily_enabled: bool
    daily_time: str
    weekly_enabled: bool
    weekly_weekday: int
    weekly_time: str
    timezone: str
    daily_next_at: str | None
    weekly_next_at: str | None


class DigestRunOut(ContractModel):
    id: str
    kind: str
    status: str
    note_id: str | None
    period_start: str
    period_end: str
    scheduled_at: str
    error: str | None


class DigestRunListOut(DigestRunOut):
    note_active: bool
    note_archived: bool


class DigestListOut(ContractModel):
    items: list[DigestRunListOut]
    next_offset: int | None
