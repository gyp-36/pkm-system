"""助手回答/分析/分类响应契约。

CitationOut 只暴露浏览器真正需要的字段（打开来源笔记）：引用编号、笔记 id、标题，
不含内部偏移/版本/原文引用。
"""

from app.contracts.base import ContractModel


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
    pending_operation: dict | None = None
    operation_receipts: list[dict] = []


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
