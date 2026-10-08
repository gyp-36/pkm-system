"""检索命中与检索响应的契约。

坐标字段（start_offset/end_offset/version/snippet）是**合法载荷**：前端
（web/src/App.vue 的 openNote）据此跳转定位原文。它们只允许出现在本模块，
见 contracts/base.py 的 COORDINATE_ALLOW。
"""

from app.contracts.base import ContractModel


class SearchHitOut(ContractModel):
    note_id: str
    title: str
    notebook_id: str | None
    version: int
    source_field: str
    content_kind: str
    location: dict | None
    start_offset: int
    end_offset: int
    snippet: str
    updated_at: str
    score: float
    match_source: str


class SearchResponseOut(ContractModel):
    items: list[SearchHitOut]
    semantic_status: str
