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
    scope: str | None = None
    missing: list[str] = field(default_factory=list)
    draft_requested: bool = False

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


BODY_MARKER = re.compile(
    r"(?:这是|以下是)(?:正文|内容|文本)\s*[:：]?|"
    r"正文(?:为|是)?(?:下面引号内的资料)?\s*(?:[:：]|(?=[“\"‘「『\n#]))|"
    r"内容\s*(?:为|是|[:：])|以下(?:资料|文本|内容)\s*[:：]|```"
)
POLITE_PREFIX = re.compile(r"^(?:(?:请你|请|麻烦你|麻烦|帮我|帮忙|协助我)\s*)+")


def request_parts(question: str) -> tuple[str, str | None]:
    """Separate an explicit payload, never an ordinary '增加一段内容' clause."""
    match = BODY_MARKER.search(question)
    if match is None:
        return question, None
    return question[:match.start()], question[match.end():]


def edit_scope(text: str) -> str | None:
    paragraph = re.search(r"第([一二三四五六七八九十\d]+)段", text)
    if paragraph:
        value = paragraph.group(1)
        number = int(value) if value.isdigit() else "一二三四五六七八九十".find(value) + 1
        return f"paragraph:{number}" if 1 <= number <= 100 else None
    if re.search(r"结尾|末尾|追加", text):
        return "append"
    if re.search(r"开头|前面", text):
        return "prepend"
    return None


def paragraph_range(body: str, number: int) -> tuple[int, int] | None:
    """Select prose paragraphs while retaining all other Markdown bytes."""
    paragraphs = []
    fenced = False
    for match in re.finditer(r"\S[\s\S]*?(?=\r?\n[ \t]*\r?\n|\Z)", body):
        block = match.group()
        if block.count("```") % 2 or block.count("~~~") % 2:
            fenced = not fenced
            continue
        if fenced or block.startswith(("#", ">", "```", "~~~")) or re.fullmatch(r"[-*_\s]+", block):
            continue
        paragraphs.append((match.start(), match.end()))
    return paragraphs[number - 1] if 1 <= number <= len(paragraphs) else None


def _target_title(prefix: str, command: str) -> str | None:
    quoted = re.search(r"《([^》]+)》", prefix)
    if quoted:
        return quoted.group(1)
    patterns = (
        r"^(?:润色|重写|改写)(?:我的)?\s*(.+?)(?:这个小说|这篇小说|小说)(?:的章节|章节)",
        r"^(?:修改|更新|改写|替换|追加|润色|重写|补充)(?:我的)?\s*(.+?)(?:笔记|文档|这篇文章|这篇日记)(?:的|[，,。\s]|$)",
        r"^(?:修改|更新|改写|替换|追加|润色|重写)(?:我的)?\s*(.+?)(?:的)?(?:第[一二三四五六七八九十\d]+段|第一章|全文|整篇|结尾|开头)",
        r"^(?:增加|添加|追加|补充).{0,20}?(?:在|到|给)(.+?)(?:这篇文章|这篇笔记|笔记|文章|的结尾)",
        r"^(?:在|给|为|向)(.+?)(?:这篇文章|这篇笔记|笔记|文章|的结尾|的开头)",
    )
    for pattern in patterns:
        match = re.search(pattern, command)
        if match:
            value = re.sub(r"(?:这篇|那篇|的)$", "", match.group(1).strip()).strip()
            if value and value not in {"它", "这篇", "那篇", "刚才的", "上面的"}:
                return value
    return None


def parse_intent(question: str) -> Intent:
    text = control_text(question).strip()
    # JSON, fenced code, quoted commands and document excerpts are data.
    prefix, body_data = request_parts(text)
    if body_data is not None:
        prefix += _after_quoted_body(body_data)
    directive = re.sub(r'[“"‘][^”"’]*[”"’]', "[资料]", prefix)
    directive = re.sub(r"《[^》]*》", "《标题》", directive)
    command = POLITE_PREFIX.sub("", directive).strip()
    command = re.sub(r"^重新(?=润色|改写|重写|修改)", "", command)
    if re.match(r"^(?:把|将|修改|更新|改写|替换|追加|润色|重写)", command):
        # A ban on creating a replacement does not revoke a requested edit.
        directive = re.sub(r"(?:不要|别|无需|不必|先不|暂不)\s*(?:再)?(?:创建|新建)(?:新)?笔记[^，,。；;]*", "", directive)
    if re.search(r"撤回|撤销|取消|不做任何改动|先别执行|不实际操作|不执行|只(?:要|给|展示|生成).*(?:草稿|预览)|(?:不要|别|无需|不必|先不|暂不).*(?:保存|创建|新建|修改|改动|写入)|仅当|如果|假设|反例|分析.*(?:语法|句话)|解释|步骤|代码示例|根据.*(?:工具|授权)|忽略.*规则", directive):
        draft_requested = bool(re.search(r"只(?:要|给|展示|生成).*(?:草稿|预览)", directive)) and not bool(re.search(r"解释|语法|反例|根据.*工具|JSON", directive))
        return Intent(reason="未获得当前直接操作授权", draft_requested=draft_requested)
    if re.search(r"要不要|能否|是否|可否|该不该", directive) or (directive.endswith(("?", "？", "吗", "么")) and not POLITE_PREFIX.match(directive)):
        return Intent(reason="能力询问不是操作授权")
    command = POLITE_PREFIX.sub("", directive).strip()
    command = re.sub(r"^重新(?=润色|改写|重写|修改)", "", command)
    new_note = re.match(r"^(?:新建|创建|新增|保存为|保存成|存为)(?:\s*[一二三四五六七八九十\d]+\s*[篇个])?(?:新)?(?:《[^》]+》)?(?:笔记|文章|日记|记录)", command)
    save_data = re.match(r"^(?:(?:把|将).{1,120}?(?:写入|存入|保存到|保存进|加入|收录到)(?:我的)?(?:知识库|笔记)|(?:保存|写入|存入|收录)(?:这篇|这份|刚才|上面|当前|文章|教程|日记|草稿|到知识库))", command)
    create_followup = re.fullmatch(r"(?:直接|立即|现在|马上|重新)?(?:创建|保存|写入)(?:笔记|这篇|这份|上述内容)?[。！!]?", command)
    if re.search(r"(?:不需要|不用|无需)修改[,，\s]*直接创建", command):
        create_followup = True
    if new_note or save_data or create_followup:
        count_match = re.search(r"([\d一二三四五六七八九十]+)[篇个]", directive)
        number = count_match.group(1) if count_match else "1"
        count = int(number) if number.isdigit() else "一二三四五六七八九十".index(number) + 1 if len(number) == 1 else 0
        if not 1 <= count <= 10:
            return Intent(reason="请明确不超过十篇的新建数量")
        raw_prefix, raw_body = request_parts(question)
        title = re.search(r"《([^》]+)》", raw_prefix) or re.search(r"标题\s*[:：]?\s*([^，,。\n]+)", raw_prefix)
        return Intent(action="create", fields=["title", "body_md"], mode="create", count=count,
                      create_title=title.group(1) if title else None,
                      create_body=_unquote(raw_body) if raw_body is not None else None,
                      missing=["body_md"] if raw_body is None and not re.search(r"主题|关于|写一篇|生成|撰写", command) else [])
    is_edit = bool(re.match(r"^(?:把|将|修改|更新|改写|替换|追加|润色|重写|增加|添加|补充|在|给|为|向)", command))
    edit_followup = bool(re.fullmatch(r"(?:重新写入|写回|(?:选(?:择)?|用)[A-Ea-e]版(?:替换|写入|保存)?)[。！!]?", command))
    raw_prefix, _ = request_parts(question)
    target_title = _target_title(raw_prefix, POLITE_PREFIX.sub("", raw_prefix).removeprefix("重新"))
    if not is_edit and not edit_followup:
        drafting = bool(re.match(r"^(?:我想(?:要)?|想)?(?:写|撰写|生成|起草)(?:一|两|二|三|\d|个|篇|份|段|文章|日记|教程)", command))
        return Intent(draft_requested=drafting, reason="生成草稿，不授权保存" if drafting else "目标或操作不明确")
    if target_title is None:
        # A paste-only polishing request has no authority over saved notes.
        if body_data is not None and re.match(r"^(?:润色|重写|改写).*(?:这段|以下|粘贴)", command):
            return Intent(draft_requested=True, reason="仅处理粘贴资料")
        if not edit_followup and not re.search(r"笔记|文章|日记|第.+段|结尾|开头|全文|整篇", command):
            return Intent(reason="目标或操作不明确")
        return Intent(action="update", fields=["body_md"], mode="preview", scope=edit_scope(command), missing=["target_title"])
    title_change = re.search(r"(?:标题|名称)(?:替换|修改|更新|改)?(?:为|成)\s*《([^》]+)》", question)
    if title_change:
        return Intent(action="update", target_title=target_title, fields=["title"], mode="title", new=title_change.group(1))
    tail = text.split("》", 1)[1] if "》" in text else text.split("笔记", 1)[1] if "笔记" in text else text
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
    return Intent(action="update", target_title=target_title, fields=["body_md"], mode="preview", scope=edit_scope(command), reason="请确认具体修改差异")


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
