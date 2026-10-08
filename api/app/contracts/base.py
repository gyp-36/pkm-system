"""响应与模型载荷的字段边界：拒绝清单、坐标允许集、契约基类。

这是"从源头截断"的地基：把"哪些字段可以离开进程、哪些字段可以进入模型"
变成可被门禁（scripts/contract_check.py）断言的常量，而不是散落在各处的约定。
"""

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """所有响应契约模型的基类。

    ``extra="forbid"`` 是强制边界且"响亮失败"：
    - handler 声明 ``response_model`` 后，FastAPI 会**经本模型**校验并序列化返回值；
    - 序列化器多带一个未声明字段 → 直接 ResponseValidationError（不泄漏、悄悄丢弃），
      这正是我们要的——新增字段必须先过契约，而不是靠人肉看代码。
    """

    model_config = ConfigDict(extra="forbid")


# 任何 API 响应都不得出现的字段名。
API_DENYLIST: frozenset[str] = frozenset({
    "embedding",
    "password_hash",
    "token_hash",
    "storage_key",
})
# 以这些后缀结尾的字段名同样禁止出现在响应里（如 xxx_secret、xxx_api_key）。
API_DENY_SUFFIXES: tuple[str, ...] = ("_secret", "_api_key", "_password")


# 任何送进模型上下文的 tool 载荷都不得出现的字段名（比 API 更严）。
# 覆盖内部主键、版本号、偏移、原文引用与一切机密列。
MODEL_DENYLIST: frozenset[str] = API_DENYLIST | frozenset({
    "id",
    "user_id",
    "note_id",
    "notebook_id",
    "tag_id",
    "note_version",
    "content_version",
    "version",
    "start_offset",
    "end_offset",
    "quote",
    "location",
    "sha256",
})


# 字符偏移字段：真·内部定位信息，只有"跳转定位原文"的功能需要（检索命中/分块/引用）。
# 只允许出现在下面登记的具体 (模块, 模型) 内；其它响应模型声明它即门禁失败。
# 注意：note_id / version 是正常资源标识（前端打开笔记、乐观并发都要用），不属于受限字段。
COORDINATE_FIELDS: frozenset[str] = frozenset({
    "start_offset",
    "end_offset",
})
COORDINATE_ALLOW: frozenset[tuple[str, str]] = frozenset({
    ("search", "SearchHitOut"),
    ("notes", "NoteChunkOut"),
})


def is_api_denied(field: str) -> bool:
    """字段名是否被 API 拒绝清单命中（含后缀规则）。"""
    return field in API_DENYLIST or field.endswith(API_DENY_SUFFIXES)
