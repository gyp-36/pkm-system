"""模型上下文的唯一信封构造器。

每个工具的结果都必须经 ``tool_result(kind, payload)`` 构造。任何不在白名单里的
key（含嵌套）会在**构造期**直接 ``KeyError``——工具在代码层面就无法产出一个
带内部字段（note_id/版本/偏移/quote 等）的载荷，而不是"事后过滤"。

运行时与门禁（scripts/contract_check.py）共用同一份 ``ENVELOPES``，因此
"工具实际能发什么"与"门禁认为能发什么"同源，构造上不可能漂移。
"""

import json
import re

from app.contracts.base import MODEL_DENYLIST
from app.assistant.data_contract import validate_shape


# 笔记正文里应用自身的内部笔记链接带数据库 UUID；进入模型前统一去掉目标。
NOTE_LINK_TARGET = re.compile(r"(#/notes\?note=)[0-9a-fA-F-]{36}")

# 顶层信封：payload 为 dict 时按其 key 集合校验；``list`` 为 True 时 payload 是
# 由同构 dict 组成的列表。
ENVELOPES: dict[str, dict] = {
    "search_hits": {
        "keys": frozenset({
            "source_ref", "note_ref", "title", "source_field", "excerpt",
            "evidence_kind", "related_to", "untrusted",
        }),
        "list": True,
    },
    "note_full": {
        "keys": frozenset({
            "note_ref", "title", "body_md", "related_image_context", "citations", "untrusted",
        }),
        "nested": {"related_image_context": "image_ref", "citations": "citation"},
    },
    "title_candidates": {
        "keys": frozenset({"status", "truncated", "candidates"}),
        "nested": {"candidates": "title_candidate"},
    },
    "external_link_ok": {
        "keys": frozenset({
            "status", "source_url", "final_url", "title", "author", "published_at",
            "markdown", "metadata", "fetched_at", "extraction_method", "untrusted",
            "error_code", "error_message",
        }),
    },
    "external_link_error": {
        "keys": frozenset({"status", "source_url", "untrusted", "error_code", "error_message"}),
    },
    "note_created": {"keys": frozenset({"status", "note_ref", "title"})},
    "note_updated": {"keys": frozenset({"status", "note_ref", "title"})},
    "note_duplicate": {"keys": frozenset({"status", "note_ref", "title"})},
}

# 嵌套信封：列表元素的 key 集合。
NESTED_ENVELOPES: dict[str, frozenset[str]] = {
    "image_ref": frozenset({"source_ref", "note_ref", "title", "description"}),
    "citation": frozenset({"source_ref", "note_ref", "source_field", "excerpt"}),
    "title_candidate": frozenset({"index", "note_ref", "title", "notebook", "updated_at"}),
}

# Every field has a concrete type. Open dictionaries are not permitted; new
# metadata fields require explicit purpose review and schema registration.
SCALAR_TYPES = {
    "untrusted": bool, "truncated": bool, "index": int,
    "author": (str, type(None)), "published_at": (str, type(None)),
    "notebook": (str, type(None)), "metadata": {},
    "error_code": (str, type(None)), "error_message": (str, type(None)),
}


def envelope_schema(envelope):
    schema = {key: SCALAR_TYPES.get(key, str) for key in envelope["keys"]}
    for key, nested in envelope.get("nested", {}).items():
        schema[key] = [{field: SCALAR_TYPES.get(field, str) for field in NESTED_ENVELOPES[nested]}]
    return schema


def _sanitize(value):
    """对载荷里的所有字符串做内部链接 UUID 脱敏。"""
    if isinstance(value, str):
        return NOTE_LINK_TARGET.sub(r"\1", value)
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    return value


def _reject(where: str, extra: set[str]) -> None:
    raise KeyError(f"tool_result envelope rejected unexpected keys at {where}: {sorted(extra)}")


def _validate_dict(kind: str, envelope: dict, item: dict, where: str) -> None:
    validate_shape(item, envelope_schema(envelope), path=where)
    allowed = envelope["keys"]
    extra = set(item) - allowed
    if extra:
        _reject(where, extra)
    for field, nested_kind in (envelope.get("nested") or {}).items():
        nested_value = item.get(field)
        if nested_value is None:
            continue
        if not isinstance(nested_value, list):
            raise KeyError(f"tool_result nested field {kind}.{field} must be a list")
        nested_keys = NESTED_ENVELOPES[nested_kind]
        for entry in nested_value:
            if not isinstance(entry, dict):
                raise KeyError(f"tool_result nested field {kind}.{field} entries must be objects")
            nested_extra = set(entry) - nested_keys
            if nested_extra:
                _reject(f"{where}.{nested_kind}", nested_extra)


def tool_result(kind: str, payload) -> str:
    """构造一个模型可见的工具结果（JSON 字符串）。

    ``payload`` 为 dict（单条）或 list（同构多条，仅 search_hits 支持）。
    key 不在该 kind 的信封内、或命中 MODEL_DENYLIST，都会在构造期抛 KeyError。
    """
    if kind not in ENVELOPES:
        raise KeyError(f"tool_result unknown envelope kind: {kind!r}")
    envelope = ENVELOPES[kind]
    if envelope.get("list"):
        if not isinstance(payload, list):
            raise KeyError(f"tool_result {kind} expects a list payload")
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                raise KeyError(f"tool_result {kind} list entries must be objects")
            _validate_dict(kind, envelope, item, f"{kind}[{index}]")
    else:
        if not isinstance(payload, dict):
            raise KeyError(f"tool_result {kind} expects an object payload")
        _validate_dict(kind, envelope, payload, kind)
    return json.dumps(_sanitize(payload), ensure_ascii=False)


def assert_envelopes_clean() -> None:
    """门禁入口：所有信封（含嵌套）都不得与 MODEL_DENYLIST 相交。"""
    for kind, envelope in ENVELOPES.items():
        overlap = envelope["keys"] & MODEL_DENYLIST
        if overlap:
            raise AssertionError(f"envelope {kind} exposes denied fields: {sorted(overlap)}")
    for nested_kind, keys in NESTED_ENVELOPES.items():
        overlap = keys & MODEL_DENYLIST
        if overlap:
            raise AssertionError(f"nested envelope {nested_kind} exposes denied fields: {sorted(overlap)}")
