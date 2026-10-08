"""开发追踪响应契约。"""

from app.contracts.base import ContractModel


class TraceOut(ContractModel):
    id: str
    user_id: str
    conversation_id: str | None
    assistant_message_id: str | None
    entrypoint: str
    model_name: str | None
    status: str
    error_type: str | None
    started_at: str
    finished_at: str | None
    duration_ms: int | None
    steps: list[dict]


class TraceListOut(ContractModel):
    items: list[TraceOut]
    total: int
    limit: int
    offset: int


class TraceEnabledOut(ContractModel):
    enabled: bool
