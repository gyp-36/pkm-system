"""笔记模板响应契约。"""

from app.contracts.base import ContractModel


class NoteTemplateOut(ContractModel):
    id: str
    name: str
    title: str
    body_md: str
    created_at: str
    updated_at: str
