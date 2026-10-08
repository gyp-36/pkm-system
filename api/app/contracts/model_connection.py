"""模型连接响应契约（不暴露 API Key 明文）。"""

from app.contracts.base import ContractModel


class ModelConnectionOut(ContractModel):
    configured: bool
    provider: str | None
    model_name: str | None
    key_masked: str | None
    updated_at: str | None


class ConnectionTestOut(ContractModel):
    ok: bool
    model_name: str
