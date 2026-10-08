"""链接草稿与文档编辑器响应契约。"""

from app.contracts.base import ContractModel


class LinkDraftOut(ContractModel):
    id: str
    source_url: str
    title: str
    snapshot_text: str
    body_md: str
    fetch_status: str
    fetch_error: str | None
    status: str
    notebook_id: str | None
    created_at: str
    updated_at: str


class LinkDraftListOut(ContractModel):
    items: list[LinkDraftOut]


class LinkDraftRewriteOut(LinkDraftOut):
    rewrite_suggestion: str


class DuplicateCheckOut(ContractModel):
    exists: bool
    note_id: str | None = None
    title: str | None = None
    filename: str | None = None


class EditorConfigOut(ContractModel):
    available: bool
    message: str | None = None
    api_url: str | None = None
    token: str | None = None
    documentType: str | None = None
    document: dict | None = None
    editorConfig: dict | None = None
    width: str | None = None
    height: str | None = None


class ContentAnalysisOut(ContractModel):
    summary: str
    key_points: list[str]
    action_suggestions: list[str]


class OnlyofficeCallbackOut(ContractModel):
    error: int
