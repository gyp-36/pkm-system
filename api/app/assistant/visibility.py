"""Purpose-specific text projection, independent of the model's self labels.

Resource coordinates belong to server state and source cards, never generated
prose. Literal user/document text is data: it is not globally UUID-filtered.
This is a last defensive projection, not a replacement for typed tool inputs.
"""
import base64
import re


SAFE_TEXT = "这部分内容包含不可公开的内部信息，已省略。请使用笔记标题描述需要处理的内容。"
# These describe control-plane fields, not software versions/array offsets.
CONTROL_LABEL = re.compile(
    r"(?:内部|数据库|internal)[\s\w\u4e00-\u9fff]{0,12}(?:ID|UUID|标识|索引|版本|偏移)|"
    r"(?:笔记|note)[ \t]*(?:ID|UUID)|"
    r"\b(?:note_id|user_id|notebook_id|note_version|content_version|start_offset|end_offset)\b[\"']?\s*[:=：]|"
    r"(?:片段|检索|索引)(?:起始|终止|起点|终点|起止|字符)?偏移|"
    r"\b(?:note|database|resource)[ _-]*(?:id|version|offset)\s*[:=：]", re.I)


def identity_forms(value: str) -> set[str]:
    """Representations of registered identities, never arbitrary user UUIDs."""
    compact = value.replace("-", "")
    forms = {value, compact, base64.b64encode(value.encode()).decode(), value.encode().hex()}
    for size in range(8, len(value)):
        forms.update((value[:size] + "…", value[:size] + "...", "…" + value[-size:], "..." + value[-size:]))
    return forms


def project_text(text: str, *, identities=(), literals=()) -> str:
    if not isinstance(text, str):
        return SAFE_TEXT
    allowed = [value for value in literals if isinstance(value, str) and value]
    # Preserve exact documentary lines, including instruction-shaped articles.
    def literal(value):
        return bool(value.strip()) and any(value.strip() in source for source in allowed)

    result = text
    for value in identities:
        if not isinstance(value, str) or not value:
            continue
        for form in sorted(identity_forms(value), key=len, reverse=True):
            if any(form.casefold() in source.casefold() for source in allowed):
                continue
            result = re.sub(re.escape(form), "[内部标识已省略]", result, flags=re.I)
    # Remove the complete control-metadata clause, not just an ID/number. This
    # also covers legacy rows whose original server evidence no longer exists.
    clauses = re.split(r"([。！？\n])", result)
    for index in range(0, len(clauses), 2):
        clause = clauses[index]
        if CONTROL_LABEL.search(clause) and not literal(clause):
            clauses[index] = "[内部信息已省略]"
    result = "".join(clauses).strip()
    return result or SAFE_TEXT


def project_history(messages: list[dict] | None) -> list[dict]:
    """Only text user/assistant roles survive; no historical tool authority."""
    projected = []
    literals = []
    for message in messages or []:
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
            continue
        content = message.get("content")
        if isinstance(content, str):
            if message["role"] == "user":
                literals.append(content)
            projected.append({"role": message["role"], "content": content if message["role"] == "user" else project_text(content, literals=literals)})
    return projected
