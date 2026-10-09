"""助手回答/分析/分类响应契约。

CitationOut 只暴露浏览器真正需要的字段（打开来源笔记）：引用编号、笔记 id、标题，
不含内部偏移/版本/原文引用。
"""

from app.contracts.base import ContractModel
from typing import Literal


class OperationReceiptOut(ContractModel):
    action: Literal["created", "updated", "already_exists"]
    title: str


class SelectionCandidateOut(ContractModel):
    index: int
    title: str
    notebook: str | None = None


class TitleFieldsOut(ContractModel):
    title: str


class BodyFieldsOut(ContractModel):
    body_md: str


class NoteFieldsOut(ContractModel):
    title: str
    body_md: str


class ChangePreviewOut(ContractModel):
    title: str
    before: NoteFieldsOut
    after: TitleFieldsOut | BodyFieldsOut | NoteFieldsOut


class PendingSelectionOut(ContractModel):
    operation_id: str
    kind: Literal["selection"]
    candidates: list[SelectionCandidateOut]


class PendingConfirmationOut(ContractModel):
    operation_id: str
    kind: Literal["confirmation"]
    changes: list[ChangePreviewOut]


class PendingInputOut(ContractModel):
    operation_id: str
    kind: Literal["input"]
    action: Literal["create", "update"]
    missing: list[Literal["target_title", "body_md", "title"]]


class CitationOut(ContractModel):
    citation_id: str
    note_id: str
    title: str


class AnswerOut(ContractModel):
    answer: str
    citations: list[CitationOut]
    semantic_status: str
    answer_source: str
    retrieval_status: str = "unknown"
    pending_operation: PendingSelectionOut | PendingConfirmationOut | PendingInputOut | None = None
    operation_receipts: list[OperationReceiptOut] = []


class AnalyzeOut(ContractModel):
    analysis: str
    suggestions: list[str]
    citations: list[CitationOut]


class ClassifyOut(ContractModel):
    note_id: str
    note_version: int
    notebook_id: str | None
    tag_ids: list[str]
    reason: str
