"""文件上传会话响应契约。"""

from app.contracts.base import ContractModel
from app.contracts.notes import NoteOut


class UploadSessionOut(ContractModel):
    id: str
    status: str
    filename: str
    size_bytes: int
    sha256: str
    part_size: int
    part_count: int
    uploaded_parts: list[dict]
    expires_at: str
    created_at: str
    note_id: str | None
    duplicate_note_id: str | None
    last_error: str | None
    part_url: str | None


class UploadSessionListOut(ContractModel):
    items: list[UploadSessionOut]


class DuplicateRefOut(ContractModel):
    id: str
    title: str
    filename: str | None = None


class UploadActionResultOut(ContractModel):
    """complete / retry / merge 的联合结果（pending|completed|duplicate|completing）。"""

    status: str
    note: NoteOut | None = None
    duplicate: DuplicateRefOut | None = None
    message: str | None = None


class PartUrlOut(ContractModel):
    url: str
    size_bytes: int
    expires_in: int


class PartsReceiptOut(ContractModel):
    uploaded_parts: list[dict]
