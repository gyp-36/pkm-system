"""笔记本与标签的响应契约。"""

from app.contracts.base import ContractModel


class ClassificationOut(ContractModel):
    id: str
    name: str
    note_count: int | None = None
