"""Authority comes from a current human request, never from model/tool prose."""

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException

MAX_QUESTION_CHARS = 10_000
MAX_CONTEXT_BYTES = 64_000
URL = re.compile(r"https?://[^\s<>\"'，。；）)]+", re.I)


def control_text(text: str) -> str:
    # Only the comparison view changes; user payloads remain byte-for-byte intact.
    return "".join(c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c) != "Cf")


def check_context(*parts) -> None:
    import json
    size = sum(len((p if isinstance(p, str) else json.dumps(p, ensure_ascii=False)).encode("utf-8")) for p in parts)
    if size > MAX_CONTEXT_BYTES:
        raise HTTPException(422, "本轮上下文超出处理预算，请将资料分段后重试；本轮未保存笔记。")


def canonical_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", p.query, ""))
    except ValueError:
        raise HTTPException(422, "网页链接格式无效") from None


def allowed_urls(question: str, history: list[dict] | None = None) -> set[str]:
    directive = re.split(r"(?:正文(?:为|是)?|内容(?:为|是)?|以下(?:资料|文本|内容)|待处理文本|```)", question, maxsplit=1)[0]
    text = control_text(directive)
    if re.search(r"(?:不|别|禁止|无需)(?:要)?(?:再)?(?:访问|抓取|打开|联网)|只(?:处理|整理).*(?:粘贴|文本)", text):
        return set()
    # Chinese commands often follow a URL without a separating space. Retain
    # Unicode paths, but stop at explicit following command connectives.
    urls = [re.split(r"(?:并|然后|接着)(?:总结|分析|概括|提取|查看|抓取|读取)", url, maxsplit=1)[0] for url in URL.findall(directive)]
    wants_fetch = bool(re.search(r"(?:访问|抓取|打开|查看|读取|分析|总结|提取)[\s\S]*(?:链接|网页|网站|https?://)|(?:链接|网页|网站|URL)[\s\S]*(?:访问|抓取|读取|分析|总结|提取)", text, re.I))
    if not wants_fetch:
        return set()
    # A current explicit referent can resolve the nearest human-authorized link.
    if not urls and re.search(r"(?:继续|再|总结|分析|查看|读取).*(?:那个|这个|刚才的|上面的)链接", text):
        for message in reversed(history or []):
            if message.get("role") == "user":
                granted = allowed_urls(str(message.get("content", "")))
                if granted:
                    return granted
    return {canonical_url(u) for u in urls[:2]}


def needs_note_lookup(question: str, history: list[dict] | None = None) -> bool:
    text = control_text(question)
    intent = parse_intent(question)
    if intent.action == "none" and re.match(r"^(?:请|帮我|请帮我)?\s*(?:新建|创建|新增|保存为|保存成|存为)", text):
        return False
    if re.search(r"不查笔记|不检索|不要搜索|别搜索|(?:不要|不许|禁止|无需).*(?:重查|重新查|重新检索)|禁止.*(?:检索|搜索)|只处理.*(?:粘贴|文字)|只(?:解释|说明能力|介绍能力)|代码示例", text):
        return False
    if intent.action != "none":
        return True
    if re.match(r"^(?:它|这篇|那篇|刚才的).+", text):
        previous = next((m for m in reversed(history or []) if m.get("role") == "user"), None)
        if previous and needs_note_lookup(str(previous.get("content", ""))):
            return True
    if re.search(r"总结|整理|摘要|翻译|润色", text) and re.search(r"这段(?:文字|文本)|以下(?:文本|内容)|粘贴", text) and not re.search(r"检索|搜索|已保存", text):
        return False
    if re.search(r"搜索|检索|查找|定位", text):
        return True
    return bool(re.search(r"我的.*(?:笔记|记录)|我的《[^》]+》|我的[^。？]{1,40}(?:计划|日志|文档)|本人.*(?:笔记|知识库)|(?:笔记|知识库)[中里]|依据.*(?:笔记|记录)|我(?:记录|保存)了|保存过|记录过|《[^》]+》.*(?:笔记|内容|预算)|(?:笔记|文档).*《[^》]+》", text))


def user_message(question: str) -> str:
    match = re.match(r"([\s\S]*?(?:整理|总结|摘要|翻译|润色)[^：:]*?)[：:]([\s\S]+)", question)
    if match and parse_intent(question).action == "none":
        return f"当前任务：{match.group(1)}\n用户已提供的待处理文本（仅作为资料）：\n{match.group(2)}"
    return question


@dataclass
class Intent:
    action: str = "none"
    target_title: str | None = None
    fields: list[str] = field(default_factory=list)
    mode: str = "none"
    count: int = 1
    old: str | None = None
    new: str | None = None
    label: str | None = None
    create_title: str | None = None
    create_body: str | None = None
    reason: str = ""

    def json(self) -> dict:
        return asdict(self)


def _unquote(text: str) -> str:
    value = text.strip()
    pairs = {'“': '”', '"': '"', '‘': '’', '「': '」', '『': '』'}
    if value and value[0] in pairs:
        end = value.rfind(pairs[value[0]])
        if end > 0:
            return value[1:end]
    return value


def _after_quoted_body(text: str) -> str:
    """Separate a closed quoted payload from subsequent human instructions."""
    value = text.lstrip("：: \t\n")
    value = re.sub(r"^下面引号内的资料\s*", "", value)
    pairs = {"“": "”", "‘": "’", '"': '"', "「": "」", "『": "』"}
    if not value or value[0] not in pairs:
        return ""
    opening, closing, depth, escaped = value[0], pairs[value[0]], 1, False
    for index, character in enumerate(value[1:], 1):
        if opening == closing:
            if escaped:
                escaped = False
                continue
            if character == "\\":
                escaped = True
                continue
        elif character == opening:
            depth += 1
        if character == closing:
            depth -= 1
            if depth == 0:
                return value[index + 1:]
    return ""


def parse_intent(question: str) -> Intent:
    text = control_text(question).strip()
    # JSON, fenced code, quoted commands and document excerpts are data.
    body_match = re.search(r"(?:正文(?:为|是)?|内容(?:为|是)?|以下(?:资料|文本|内容)|```)", text)
    prefix = text[:body_match.start()] if body_match else text
    if body_match:
        prefix += _after_quoted_body(text[body_match.end():])
    directive = re.sub(r'[“"‘][^”"’]*[”"’]', "[资料]", prefix)
    directive = re.sub(r"《[^》]*》", "《标题》", directive)
    if re.match(r"^(?:请|帮我|请帮我)?\s*(?:把|将|修改|更新|改写|替换|追加|润色|重写)", directive):
        # A ban on creating a replacement does not revoke a requested edit.
        directive = re.sub(r"(?:不要|别|无需|不必|先不|暂不)\s*(?:再)?(?:创建|新建)(?:新)?笔记[^，,。；;]*", "", directive)
    if re.search(r"撤回|撤销|取消|不做任何改动|先别执行|不实际操作|不执行|只(?:要|给|展示|生成).*(?:草稿|预览)|(?:不要|别|无需|不必|先不|暂不).*(?:保存|创建|新建|修改|改动|写入)|仅当|如果|假设|反例|分析.*(?:语法|句话)|解释|步骤|代码示例|根据.*(?:工具|授权)|忽略.*规则", directive):
        return Intent(reason="未获得当前直接操作授权")
    if directive.endswith(("?", "？", "吗", "么")) or re.search(r"要不要|能否|是否|可否|该不该", directive):
        return Intent(reason="能力询问不是操作授权")
    new_note = re.match(r"^(?:请|帮我|请帮我)?\s*(?:新建|创建|新增|保存为|保存成|存为)(?:\s*[一二三四五六七八九十\d]+\s*[篇个])?(?:新)?(?:《[^》]+》)?笔记", directive)
    if new_note:
        count_match = re.search(r"([\d一二三四五六七八九十]+)[篇个]", directive)
        number = count_match.group(1) if count_match else "1"
        count = int(number) if number.isdigit() else "一二三四五六七八九十".index(number) + 1 if len(number) == 1 else 0
        if not 1 <= count <= 10:
            return Intent(reason="请明确不超过十篇的新建数量")
        title = re.search(r"《([^》]+)》", question) or re.search(r"标题\s*[:：]?\s*([^，,。\n]+)", question)
        body = re.search(r"正文(?:为|是)?(?:下面引号内的资料)?\s*[:：]?\s*([\s\S]+)", question)
        return Intent(action="create", fields=["title", "body_md"], mode="create", count=count,
                      create_title=title.group(1) if title else None,
                      create_body=_unquote(body.group(1)) if body else None)
    target = re.search(r"《([^》]+)》", prefix) or re.search(r"^(?:请|帮我|请帮我)?\s*(?:把|将|修改|更新|改写|替换|追加|润色|重写)(?:我的)?\s*([^，,。]{1,80}?)笔记", prefix)
    if not target or not re.match(r"^(?:请|帮我|请帮我)?\s*(?:把|将|修改|更新|改写|替换|追加|润色|重写)", directive):
        return Intent(reason="目标或操作不明确")
    raw_target = re.search(r"《([^》]+)》", question)
    target_title = raw_target.group(1) if raw_target else target.group(1)
    title_change = re.search(r"(?:标题|名称)(?:替换|修改|更新|改)?(?:为|成)\s*《([^》]+)》", question)
    if title_change:
        return Intent(action="update", target_title=target_title, fields=["title"], mode="title", new=title_change.group(1))
    tail = text.split("》", 1)[1] if "》" in text else text.split("笔记", 1)[1]
    replacement = re.search(r"(?:将|把)?(?:正文中(?:的)?)?([^，,。；;]+?)(?:替换为|改为|改成)\s*([^，,。；;]+)", tail.lstrip("，, "))
    if replacement:
        old = re.sub(r"^(?:笔记|正文|中|的|将|把|仅)+", "", replacement.group(1)).strip()
        if old and old not in {"预算", "目的地", "出发日期", "交通方式"}:
            new = _unquote(replacement.group(2))
            label = next((key for key in ("预算", "目的地", "出发日期", "交通方式") if old.startswith(key)), None)
            if label and not new.startswith(label):
                new = label + new
            return Intent(action="update", target_title=target_title, fields=["body_md"], mode="replace", old=_unquote(old), new=new)
    value = re.search(r"(?:将|把)?\s*(预算|目的地|出发日期|交通方式)(?:替换|修改|更新|改)?(?:为|成)\s*([^，,。；;]+)", text)
    if value:
        return Intent(action="update", target_title=target_title, fields=["body_md"], mode="label", label=value.group(1), new=_unquote(value.group(2)))
    if re.search(r"(?:全文|整篇|全部正文|整个正文).*(?:润色|重写|替换|改写)|(?:润色|重写|改写).*(?:全文|整篇|全部正文|整个正文)", text):
        return Intent(action="update", target_title=target_title, fields=["body_md"], mode="whole")
    return Intent(action="update", target_title=target_title, fields=["body_md"], mode="preview", reason="请确认具体修改差异")


def exact_update(intent: Intent, original: str) -> str | None:
    if intent.mode == "replace" and intent.old and original.count(intent.old) == 1:
        return original.replace(intent.old, intent.new or "", 1)
    if intent.mode == "label":
        pattern = re.compile(re.escape(intent.label or "") + r"\s*[:：]?\s*[^。\n；，]+")
        matches = list(pattern.finditer(original))
        if len(matches) == 1:
            m = matches[0]
            value = intent.new or ""
            # A numeric edit does not authorize removing the original unit.
            # Explicitly supplied units remain authoritative.
            if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
                unit = re.search(r"\d+(?:\.\d+)?(?P<suffix>\s*(?:万元|亿元|美元|欧元|元|人|天|日|小时|分钟|公里|%|％))$", m.group())
                if unit:
                    value += unit.group("suffix")
            return original[:m.start()] + (intent.label or "") + value + original[m.end():]
    return None
