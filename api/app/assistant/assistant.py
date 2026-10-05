"""Account-scoped note assistant with server-validated citations and guarded edits."""

import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from langchain.agents import create_agent
from langchain.messages import HumanMessage, SystemMessage
from langchain.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.auth import Db, UserId
from app.core.db import SessionLocal
from app.core.enums import AuditAction, AuditEntityType, ChunkSource
from app.core.lifecycle import record_event, record_revision
from app.knowledge.indexer import segment_note
from app.assistant.model_connection import chat_model, decrypt_key, require_connection
from app.assistant.tracing import TraceRecorder
from app.core.models import Note, Notebook, Tag
from app.knowledge.search import rag_evidence_hits
from app.knowledge.markdown_images import ImageDescription, descriptions_for_range
from app.core.rate_limit import check_limit
from app.knowledge.notes import NoteUpdate, queue_index, update_note, validate_categories
from app.prompts import load_prompt


router = APIRouter(prefix="/v1/assistant", tags=["assistant"])
log = logging.getLogger(__name__)
MARKER = re.compile(r"\[S\d+\]")
MAX_RAG_EVIDENCE = 5
MAX_KEYWORD_VARIANTS = 5
QUERY_STOP_PHRASES = (
    "请问", "告诉我", "帮我", "帮忙", "解释一下", "介绍一下", "什么是", "什么叫", "如何理解",
    "我记录了什么", "我的笔记中", "我的笔记里", "笔记中提到的", "笔记里提到的", "笔记中关于", "笔记里关于",
    "请总结", "总结一下", "有哪些", "有什么", "怎么做", "如何做", "可以吗", "是否", "请",
)
CREATE_NOTE_VERBS = ("新建", "创建", "新增", "导入")
UPDATE_NOTE_VERBS = ("更新", "修改", "改写", "覆盖", "替换", "追加", "合并")
EXTERNAL_LINK_MARKERS = re.compile(r"https?://|www\.|链接|网址|网页|外链|\burl\b", re.IGNORECASE)


def explicit_note_write_scopes(question: str) -> tuple[bool, bool]:
    """Grant per-turn create/update tools only for a direct, non-hypothetical request."""
    normalized = re.sub(r"\s+", "", question).casefold()
    if normalized.endswith(("吗", "么", "?", "？")) or any(
        phrase in normalized for phrase in ("要不要", "是否", "能否", "可否", "该不该", "应该不应该", "值不值得", "怎么", "如何", "怎样", "你觉得", "如果")
    ):
        return False, False
    targets_note = any(phrase in normalized for phrase in ("笔记", "知识库"))
    create_denied = bool(re.search(r"(?:不要|不必|无需|暂不|先不|不想|不愿|别)(?:再|去|进行|帮我)?(?:新建|创建|新增|导入|保存|存入|写入)", normalized))
    update_denied = bool(re.search(r"(?:不要|不必|无需|暂不|先不|不想|不愿|别)(?:再|去|进行|帮我)?(?:更新|修改|改写|覆盖|替换|追加|合并|写入|写进|添加|加入|放入)", normalized))
    explicit_new_note = any(phrase in normalized for phrase in ("保存为笔记", "保存成笔记", "存成笔记", "存为新笔记", "保存到新笔记", "保存到知识库", "存入知识库", "写入新笔记"))
    creates = targets_note and not create_denied and (explicit_new_note or any(verb in normalized for verb in CREATE_NOTE_VERBS))
    direct_update = any(verb in normalized for verb in UPDATE_NOTE_VERBS) and any(
        phrase in normalized for phrase in ("笔记", "正文", "内容")
    )
    write_into_existing = any(verb in normalized for verb in ("写入", "写进", "添加", "加入", "放入")) and any(
        phrase in normalized for phrase in ("现有笔记", "当前笔记", "这篇笔记", "该笔记", "目标笔记", "已有笔记")
    )
    updates = not update_denied and (direct_update or write_into_existing)
    return creates, updates


def is_note_update_selection_followup(question: str, history: list[dict] | None) -> bool:
    """Continue an explicitly authorized update after the assistant asks the user to choose a match."""
    if not history or len(history) < 2:
        return False
    previous_user, previous_assistant = history[-2:]
    if previous_user.get("role") != "user" or previous_assistant.get("role") != "assistant":
        return False
    _, previously_authorized = explicit_note_write_scopes(str(previous_user.get("content", "")))
    if not previously_authorized:
        return False

    assistant_text = previous_assistant.get("content", "")
    if not isinstance(assistant_text, str) or "请选择要修改的笔记（回复候选序号）" not in assistant_text:
        return False
    candidate_numbers = {
        int(match)
        for match in re.findall(r"(?m)^\s*(\d+)[.、)]\s+", assistant_text)
    }
    if len(candidate_numbers) < 2:
        return False

    normalized = re.sub(r"\s+", "", question).casefold()
    if any(word in normalized for word in ("不要", "不用", "取消", "算了", "不改", "先不", "暂不")):
        return False
    selected = re.search(r"(?:选择|选)?[:：]?第?(\d+|十[一二三四五六七八九]?|[二三]十|[一二三四五六七八九十])(?:篇|个|项)?", normalized)
    if not selected:
        return False
    ordinal = selected.group(1)
    if ordinal.isdigit():
        selected_number = int(ordinal)
    elif ordinal == "十":
        selected_number = 10
    elif ordinal.startswith("十"):
        selected_number = 10 + "一二三四五六七八九".index(ordinal[1]) + 1
    elif ordinal.endswith("十"):
        selected_number = ("一二三四五六七八九".index(ordinal[0]) + 1) * 10
    else:
        selected_number = "一二三四五六七八九".index(ordinal) + 1
    return selected_number in candidate_numbers


def mentions_external_link(question: str, history: list[dict] | None = None) -> bool:
    if EXTERNAL_LINK_MARKERS.search(question):
        return True
    return any(
        message.get("role") == "user"
        and isinstance(message.get("content"), str)
        and EXTERNAL_LINK_MARKERS.search(message["content"])
        for message in (history or [])[-8:]
    )


class QuestionInput(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class SelectedNoteInput(BaseModel):
    note_id: uuid.UUID


def keyword_query_variants(question: str) -> list[str]:
    """Make bounded, deterministic keyword variants without another chat-model call."""
    normalized = re.sub(r"\s+", " ", question).strip()
    for phrase in QUERY_STOP_PHRASES:
        normalized = normalized.replace(phrase, " ")

    variants: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_+#.-]*|\d+(?:[./-]\d+)*", normalized):
        token = token.strip("._-+#")
        if len(token) >= 2 and token.casefold() not in {item.casefold() for item in variants}:
            variants.append(token)

    for run in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        for size in (4, 3, 2):
            for start in range(max(0, len(run) - size + 1)):
                term = run[start : start + size]
                if term not in variants:
                    variants.append(term)
                if len(variants) >= MAX_KEYWORD_VARIANTS:
                    return variants
    return variants[:MAX_KEYWORD_VARIANTS]


def current_note(note_id: uuid.UUID, user_id: uuid.UUID) -> Note:
    with SessionLocal() as db:
        note = db.scalar(select(Note).where(Note.id == note_id, Note.user_id == user_id, Note.deleted_at.is_(None)))
        if note is None:
            raise HTTPException(status_code=404, detail="笔记不存在")
        db.expunge(note)
        return note


class Evidence:
    def __init__(self, user_id: uuid.UUID, *, max_evidence_items: int | None = None):
        self.user_id = user_id
        self.max_evidence_items = max_evidence_items
        self.items: dict[str, dict] = {}
        self._seen: dict[tuple, str] = {}
        self._lock = threading.Lock()
        self.search_calls = 0
        self.read_calls = 0
        self.semantic_status = "not_requested"

    def add(self, *, note_id: str, note_version: int, title: str, source_field: str, start_offset: int, end_offset: int, quote: str) -> dict | None:
        key = (note_id, note_version, source_field, start_offset, end_offset)
        with self._lock:
            if key in self._seen:
                return {"citation_id": self._seen[key], **self.items[self._seen[key]]}
            if self.max_evidence_items is not None and len(self.items) >= self.max_evidence_items:
                return None
            marker = f"S{len(self.items) + 1}"
            value = {
                "note_id": note_id, "note_version": note_version, "title": title,
                "source_field": source_field, "start_offset": start_offset,
                "end_offset": end_offset, "quote": quote,
            }
            self.items[marker] = value
            self._seen[key] = marker
            return {"citation_id": marker, **value}

    def add_image_description(self, description: ImageDescription) -> dict | None:
        if not description.body_md:
            return None
        return self.add(
            note_id=str(description.image_note_id),
            note_version=description.note_version,
            title=description.title,
            source_field="body",
            start_offset=0,
            end_offset=len(description.body_md),
            quote=description.body_md,
        )

    def search(self, question: str) -> str:
        with self._lock:
            self.search_calls += 1
            if self.search_calls > 2:
                return "已达到搜索次数上限，请用现有证据回答。"
            remaining = None if self.max_evidence_items is None else self.max_evidence_items - len(self.items)
        question = question.strip()
        if not question:
            return "搜索词为空。"
        if remaining == 0:
            return "本轮可提供的证据已达到上限，请根据已返回的证据回答。"

        keyword_queries = list(dict.fromkeys([question, *keyword_query_variants(question)]))
        related_images: dict[tuple, list[ImageDescription]] = {}
        with SessionLocal() as db:
            candidates, semantic_available = rag_evidence_hits(
                db,
                self.user_id,
                keyword_queries=keyword_queries,
                semantic_queries=[question],
                per_query_limit=20,
            )
            for hit in candidates[:MAX_RAG_EVIDENCE]:
                key = (hit["note_id"], hit["version"], hit["source_field"], hit["start_offset"], hit["end_offset"])
                if hit["source_field"] == "body":
                    related_images[key] = descriptions_for_range(
                        db,
                        self.user_id,
                        uuid.UUID(hit["note_id"]),
                        hit["start_offset"],
                        hit["end_offset"],
                    )
            self.semantic_status = "ready" if semantic_available else "unavailable"
        if not candidates:
            return "本人笔记中没有找到可用于回答问题的内容。请根据通用知识回答，并说明笔记没有找到合适依据。"

        # 关键词/向量混合检索及 RRF 已在工具内完成；交给 Agent 判断这些片段能否直接回答问题。
        shortlist = candidates[:MAX_RAG_EVIDENCE]
        result = []
        returned_ids: set[str] = set()
        for hit in shortlist:
            if len(result) >= MAX_RAG_EVIDENCE:
                break
            citation = self.add(
                note_id=hit["note_id"], note_version=hit["version"], title=hit["title"],
                source_field=hit["source_field"], start_offset=hit["start_offset"],
                end_offset=hit["end_offset"], quote=hit["snippet"],
            )
            if citation is None:
                break
            if citation["citation_id"] not in returned_ids:
                result.append(citation)
                returned_ids.add(citation["citation_id"])
            key = (hit["note_id"], hit["version"], hit["source_field"], hit["start_offset"], hit["end_offset"])
            for description in related_images.get(key, []):
                image_citation = self.add_image_description(description)
                if image_citation is None:
                    break
                if image_citation["citation_id"] not in returned_ids:
                    result.append({
                        **image_citation,
                        "evidence_kind": "image_description",
                        "related_to": citation["citation_id"],
                    })
                    returned_ids.add(image_citation["citation_id"])
                if len(result) >= MAX_RAG_EVIDENCE:
                    break
        if result:
            return json.dumps(result, ensure_ascii=False)
        if self.max_evidence_items is not None and len(self.items) >= self.max_evidence_items:
            return "本轮可提供的证据已达到上限，请根据已返回的证据回答。"
        return "本人笔记中没有找到可用于回答问题的内容。请根据通用知识回答，并说明笔记没有找到合适依据。"

    def read_full(self, note_id: str, *, include_citations: bool = False) -> str:
        """Return the complete current note body, without segmenting or truncating it."""
        with self._lock:
            self.read_calls += 1
            if self.read_calls > 2:
                return "已达到读取次数上限，请使用已经读取的完整内容。"
        try:
            note = current_note(uuid.UUID(note_id), self.user_id)
        except (ValueError, HTTPException):
            return "该笔记不存在或不属于当前用户。"
        result = {
            "note_id": str(note.id),
            "title": note.title,
            "version": note.version,
            "body_md": note.body_md,
        }
        with SessionLocal() as db:
            image_descriptions = descriptions_for_range(
                db, self.user_id, note.id, 0, len(note.body_md)
            ) if note.body_md else []
        related_images = []
        for description in image_descriptions:
            citation = self.add_image_description(description)
            if citation is None:
                break
            related_images.append({
                "citation_id": citation["citation_id"],
                "image_note_id": citation["note_id"],
                "title": description.title,
                "description": description.caption,
            })
        if related_images:
            result["related_image_context"] = related_images
        if include_citations:
            citations = []
            for segment in segment_note(note.title, note.body_md):
                citation = self.add(
                    note_id=str(note.id), note_version=note.version, title=note.title,
                    source_field=ChunkSource(segment.source).name.lower(),
                    start_offset=segment.start, end_offset=segment.end, quote=segment.content,
                )
                if citation is None:
                    break
                citations.append(citation)
            result["citations"] = citations
        return json.dumps(result, ensure_ascii=False)

    def verified(self, answer: str) -> list[dict]:
        mentioned = list(dict.fromkeys(marker[1:-1] for marker in MARKER.findall(answer)))
        citations = []
        with SessionLocal() as db:
            for marker in mentioned:
                if marker not in self.items:
                    continue
                item = self.items[marker]
                note = db.scalar(select(Note).where(Note.id == uuid.UUID(item["note_id"]), Note.user_id == self.user_id, Note.deleted_at.is_(None)))
                if note is None or note.version != item["note_version"]:
                    continue
                source = note.title if item["source_field"] == "title" else note.body_md
                if source[item["start_offset"]:item["end_offset"]] != item["quote"]:
                    continue
                citations.append({"citation_id": marker, **item})
        return citations


def build_agent(
    model,
    evidence: Evidence,
    system_prompt: str,
    *,
    can_search: bool,
    can_update_notes: bool = False,
    can_fetch_links: bool = False,
    can_create_notes: bool = False,
):
    fetched_links: dict[str, dict] = {}
    attempted_links: set[str] = set()

    @tool
    def search_personal_notes(question: str) -> str:
        """Search the current user's saved personal notes and knowledge base. Call this only when the user's current request asks about, refers to, or explicitly asks you to rely on information stored in their notes, knowledge base, or uploaded documents. Do not call it for greetings, general-knowledge questions, coding help, brainstorming, writing or summarizing content already present in the chat, or external-link analysis. Prior search results, citations, or conversation history alone do not authorize another search; use history only to resolve what a clearly note-related current request refers to. Pass the complete current question so relevant saved passages can be found."""
        return evidence.search(question)

    @tool
    def read_personal_note(note_id: str, include_citations: bool = False) -> str:
        """Read the complete current title, version, and Markdown body of one owned note; optionally include citation anchors. The note body is never clipped."""
        return evidence.read_full(note_id, include_citations=include_citations)

    @tool
    def find_personal_notes_by_title(title: str) -> str:
        """Find the current user's active notes by exact title, falling back to partial title matches; use this to resolve a note name before an explicitly requested edit."""
        if not can_update_notes:
            return "本轮没有授权修改笔记，未搜索修改目标。"
        title = title.strip()
        if not title:
            return json.dumps({"status": "empty_title", "candidates": []}, ensure_ascii=False)
        escaped = title.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        exact_query = (
            select(Note, Notebook.name)
            .outerjoin(Notebook, Notebook.id == Note.notebook_id)
            .where(Note.user_id == evidence.user_id, Note.deleted_at.is_(None), Note.title.ilike(escaped, escape="\\"))
            .order_by(Note.title.asc(), Note.id.asc())
        )
        with SessionLocal() as db:
            matches = db.execute(exact_query.limit(21)).all()
            if not matches:
                partial_query = (
                    select(Note, Notebook.name)
                    .outerjoin(Notebook, Notebook.id == Note.notebook_id)
                    .where(
                        Note.user_id == evidence.user_id,
                        Note.deleted_at.is_(None),
                        Note.title.ilike(f"%{escaped}%", escape="\\"),
                    )
                    .order_by(Note.title.asc(), Note.id.asc())
                )
                matches = db.execute(partial_query.limit(21)).all()
        truncated = len(matches) > 20
        candidates = [
            {
                "index": index,
                "note_id": str(note.id),
                "title": note.title,
                "notebook": notebook_name,
                "updated_at": note.updated_at.isoformat(),
            }
            for index, (note, notebook_name) in enumerate(matches[:20], start=1)
        ]
        return json.dumps({"status": "ok" if candidates else "not_found", "truncated": truncated, "candidates": candidates}, ensure_ascii=False)

    @tool
    def fetch_external_link(url: str) -> str:
        """Make one safe HTTP attempt for a user-provided public page and extract text only. No browser, third-party reader, recursive crawling, or retry."""
        def error(code: str, message: str) -> str:
            return json.dumps({
                "status": "error",
                "source_url": url,
                "untrusted": True,
                "error_code": code,
                "error_message": message,
            }, ensure_ascii=False)

        if url in attempted_links:
            return error("already_attempted", "本轮已尝试过该链接，不会重试。")
        if len(attempted_links) >= 2:
            return error("attempt_limit", "本轮最多尝试两个不同链接。")
        attempted_links.add(url)
        try:
            from app.knowledge.m3 import fetch_public_page_source, parse_public_page_source

            final_url, content_type, raw = fetch_public_page_source(url)
            title, content = parse_public_page_source(content_type, raw)
            if not content.strip():
                return error("empty", "网页没有提取到可用正文。")
            fetched_links[url] = {"final_url": final_url, "title": title or "网页内容", "content": content}
            return json.dumps({
                "status": "ok",
                "source_url": url,
                "final_url": final_url,
                "title": title or "网页内容",
                "author": None,
                "published_at": None,
                "markdown": content,
                "metadata": {},
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "extraction_method": "http",
                "untrusted": True,
                "error_code": None,
                "error_message": None,
            }, ensure_ascii=False)
        except HTTPException as exc:
            code = {
                403: "blocked",
                413: "too_large",
                415: "unsupported",
                422: "unsafe_or_invalid_url",
                502: "network_error",
                504: "timeout",
            }.get(exc.status_code, "fetch_failed")
            if exc.status_code == 422 and "2048" in str(exc.detail):
                code = "url_too_long"
            return error(code, str(exc.detail))
        except Exception as exc:
            log.warning("assistant link fetch failed: %s", type(exc).__name__)
            return error("fetch_failed", "网页抓取失败，本轮不会使用其他抓取策略。")

    @tool
    def create_personal_note(
        title: str,
        body_md: str,
        notebook_id: str | None = None,
        source_url: str | None = None,
    ) -> str:
        """Create a new note after the user explicitly requests creation."""
        if not can_create_notes:
            return "本轮没有授权新建笔记，未创建。"
        if not title.strip() or not body_md.strip():
            return "新建笔记需要标题和正文，未创建。"
        if len(title) > 240 or len(body_md) > 100_000:
            return "标题或正文超出长度限制，未创建笔记。"
        try:
            notebook_uuid = uuid.UUID(notebook_id) if notebook_id else None
        except ValueError:
            return "笔记本 ID 无效，未创建笔记。"
        source = None
        if source_url is not None:
            if source_url not in fetched_links:
                return "来源链接必须是本轮已抓取的链接，未创建笔记。"
            source = source_url
        try:
            with SessionLocal() as db:
                if source:
                    duplicate = db.scalar(select(Note).where(
                        Note.user_id == evidence.user_id,
                        Note.source_url == source,
                        Note.deleted_at.is_(None),
                    ))
                    if duplicate is not None:
                        return json.dumps({"status": "duplicate_link", "note_id": str(duplicate.id), "title": duplicate.title}, ensure_ascii=False)
                validate_categories(db, evidence.user_id, notebook_uuid, [])
                note = Note(
                    user_id=evidence.user_id,
                    notebook_id=notebook_uuid,
                    title=title.strip(),
                    body_md=body_md,
                    version=1,
                    content_version=1,
                    content_kind="markdown",
                    source_url=source,
                )
                db.add(note)
                db.flush()
                queue_index(db, note)
                record_revision(db, note, [])
                record_event(
                    db, evidence.user_id, AuditAction.CREATE, AuditEntityType.NOTE, note.id,
                    entity_version=note.version,
                    details={"fields": ["title", "body_md", "source_url"], "source": "assistant"},
                )
                db.commit()
                return json.dumps({"status": "created", "note_id": str(note.id), "title": note.title, "version": note.version}, ensure_ascii=False)
        except HTTPException as exc:
            return f"创建失败：{exc.detail}"
        except Exception as exc:
            log.warning("assistant note creation failed: %s: %s", type(exc).__name__, exc)
            return "创建笔记失败，未能保存。"

    @tool
    def update_personal_note(
        note_id: str,
        expected_version: int,
        title: str | None = None,
        body_md: str | None = None,
    ) -> str:
        """Update an existing note after the user explicitly requests an edit; requires the current note version."""
        if not can_update_notes:
            return "本轮没有授权修改笔记，未修改。"
        if body_md is None and title is None:
            return "没有提供要保存的正文或标题。"
        if (body_md is not None and len(body_md) > 100_000) or (title is not None and (not title.strip() or len(title) > 240)):
            return "修改内容超出长度限制或标题为空，请缩短后重试。"
        try:
            parsed_id = uuid.UUID(note_id)
        except ValueError:
            return "笔记 ID 无效。"
        try:
            with SessionLocal() as db:
                changes = {"version": expected_version}
                if title is not None:
                    changes["title"] = title
                if body_md is not None:
                    changes["body_md"] = body_md
                updated = update_note(parsed_id, NoteUpdate(**changes), db, evidence.user_id)
            return json.dumps({
                "status": "updated",
                "note_id": updated["id"],
                "title": updated["title"],
                "version": updated["version"],
            }, ensure_ascii=False)
        except HTTPException as exc:
            if exc.status_code == 409:
                return "笔记已经更新，当前修改未保存。请重新读取最新版本后再决定是否重试。"
            if exc.status_code == 404:
                return "该笔记不存在或不属于当前用户，未做修改。"
            return f"保存失败：{exc.detail}"
        except Exception as exc:
            log.warning("assistant note update failed: %s: %s", type(exc).__name__, exc)
            return "保存失败，笔记未能更新。"

    tools = [search_personal_notes, read_personal_note] if can_search else [read_personal_note]
    if can_update_notes:
        tools.append(find_personal_notes_by_title)
    if can_fetch_links:
        tools.append(fetch_external_link)
    if can_create_notes:
        tools.append(create_personal_note)
    if can_update_notes:
        tools.append(update_personal_note)
    return create_agent(model=model, tools=tools, system_prompt=system_prompt)


def invoke(agent, prompt: str | list[dict], *, trace: TraceRecorder | None = None) -> str:
    try:
        messages = prompt if isinstance(prompt, list) else [{"role": "user", "content": prompt}]
        config = {"recursion_limit": 8}
        handler = trace.callback_handler() if trace is not None else None
        if handler is not None:
            config["callbacks"] = [handler]
        result = agent.invoke({"messages": messages}, config=config)
        content = result["messages"][-1].content
        if not isinstance(content, str):
            raise ValueError("non-text assistant response")
        return content.strip()
    except Exception as exc:
        if trace is not None:
            trace.add_step("error", "Agent 执行失败", status="error", summary={"error_type": type(exc).__name__})
        log.warning("assistant invocation failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="聊天模型暂不可用，请稍后重试") from None


def summarize_conversation_context(
    existing_summary: str | None,
    messages: list[dict],
    db,
    user_id: uuid.UUID,
) -> str | None:
    """Compact older conversation turns into a small, untrusted reference summary."""
    row = require_connection(db, user_id)
    key, model_name = decrypt_key(row), row.model_name
    db.rollback()
    payload = {
        "existing_summary": existing_summary or "",
        "messages": messages,
    }
    try:
        result = chat_model(key, model_name, max_tokens=320).invoke([
            SystemMessage(content=load_prompt("conversation_summary_system.txt")),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ])
        content = result.content
        if not isinstance(content, str):
            return None
        summary = MARKER.sub("[历史引用]", content.strip())
        return summary[:1600] if summary else ""
    except Exception as exc:
        log.warning("assistant conversation summarization failed: %s", type(exc).__name__)
        return None


def parse_json_response(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
        if not isinstance(value, dict):
            raise ValueError("response must be an object")
        return value
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=502, detail="模型输出格式无效，请重试") from None


def answer_question(
    question: str,
    db,
    user_id: uuid.UUID,
    history: list[dict] | None = None,
    *,
    limit_checked: bool = False,
    trace: TraceRecorder | None = None,
) -> dict:
    row = require_connection(db, user_id)
    key, model_name = decrypt_key(row), row.model_name
    if trace is not None:
        trace.set_model_name(model_name)
    if not limit_checked:
        check_limit(user_id, "assistant", limit=10)
    db.rollback()
    model = chat_model(key, model_name)
    evidence = Evidence(user_id, max_evidence_items=MAX_RAG_EVIDENCE)
    create_requested, update_requested = explicit_note_write_scopes(question)
    update_requested = update_requested or is_note_update_selection_followup(question, history)
    link_context_requested = mentions_external_link(question, history)
    agent = build_agent(
        model,
        evidence,
        answer_system_prompt(),
        can_search=True,
        can_update_notes=update_requested,
        can_fetch_links=link_context_requested,
        can_create_notes=create_requested,
    )
    messages = list(history or [])
    messages.append({"role": "user", "content": question})
    answer = invoke(agent, messages, trace=trace)
    citations = evidence.verified(answer)
    if trace is not None:
        trace.record_evidence(evidence)
    answer = MARKER.sub("", answer)
    return {
        "answer": answer,
        "citations": citations,
        "semantic_status": evidence.semantic_status,
        "answer_source": answer_source(answer, citations),
    }


def answer_system_prompt() -> str:
    return load_prompt("answer_system.txt")


def answer_source(answer: str, citations: list[dict]) -> str:
    if not citations:
        return "model_knowledge"
    if "通用知识补充" in answer or "笔记没有找到合适依据" in answer:
        return "mixed"
    return "knowledge_base"


def stream_answer_question(
    question: str,
    db,
    user_id: uuid.UUID,
    history: list[dict] | None = None,
    *,
    limit_checked: bool = False,
    trace: TraceRecorder | None = None,
):
    """Yield answer deltas from the agent, then return the verified final answer."""
    row = require_connection(db, user_id)
    key, model_name = decrypt_key(row), row.model_name
    if trace is not None:
        trace.set_model_name(model_name)
    if not limit_checked:
        check_limit(user_id, "assistant", limit=10)
    db.rollback()
    model = chat_model(key, model_name)
    evidence = Evidence(user_id, max_evidence_items=MAX_RAG_EVIDENCE)
    create_requested, update_requested = explicit_note_write_scopes(question)
    update_requested = update_requested or is_note_update_selection_followup(question, history)
    link_context_requested = mentions_external_link(question, history)
    agent = build_agent(
        model,
        evidence,
        answer_system_prompt(),
        can_search=True,
        can_update_notes=update_requested,
        can_fetch_links=link_context_requested,
        can_create_notes=create_requested,
    )
    messages = list(history or [])
    messages.append({"role": "user", "content": question})
    answer_parts: list[str] = []
    final_answer = ""
    tools_finished = False
    config = {"recursion_limit": 8}
    handler = trace.callback_handler() if trace is not None else None
    if handler is not None:
        config["callbacks"] = [handler]
    try:
        events = agent.stream(
            {"messages": messages},
            config=config,
            stream_mode=["messages", "updates"],
            version="v2",
        )
        while True:
            try:
                chunk = next(events)
            except StopIteration:
                break
            if chunk.get("type") == "messages":
                token, metadata = chunk["data"]
                # Agent 消息流包含用于选择工具的模型输出和嵌套的改写调用。
                # 只有检索完成后的模型轮次才是回答正文。
                if not tools_finished or metadata.get("langgraph_node") != "model":
                    continue
                if getattr(token, "tool_call_chunks", None) or getattr(token, "tool_calls", None):
                    continue
                content = token.content
                if isinstance(content, str):
                    delta = content
                elif isinstance(content, list):
                    delta = "".join(
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict) and block.get("type") in {"text", "output_text"}
                    )
                else:
                    delta = ""
                if delta:
                    answer_parts.append(delta)
                    yield {"type": "delta", "text": delta}
            elif chunk.get("type") == "updates":
                update = chunk.get("data", {})
                if "tools" in update:
                    tools_finished = True
                    answer_parts.clear()
                    continue
                model_update = update.get("model", {})
                updated_messages = model_update.get("messages", []) if isinstance(model_update, dict) else []
                if updated_messages:
                    message = updated_messages[-1]
                    if not getattr(message, "tool_calls", None) and isinstance(getattr(message, "content", None), str):
                        final_answer = message.content.strip()
    except Exception as exc:
        if trace is not None:
            trace.add_step("error", "Agent 执行失败", status="error", summary={"error_type": type(exc).__name__})
        log.warning("assistant streaming invocation failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="聊天模型暂不可用，请稍后重试") from None

    if not final_answer:
        final_answer = "".join(answer_parts).strip()
    if not final_answer:
        raise HTTPException(status_code=502, detail="聊天模型未返回回答，请稍后重试")
    citations = evidence.verified(final_answer)
    if trace is not None:
        trace.record_evidence(evidence)
    final_answer = MARKER.sub("", final_answer)
    return {
        "answer": final_answer,
        "citations": citations,
        "semantic_status": evidence.semantic_status,
        "answer_source": answer_source(final_answer, citations),
    }


@router.post("/ask")
def ask(body: QuestionInput, db: Db, user_id: UserId) -> dict:
    connection = require_connection(db, user_id)
    trace = TraceRecorder("ask", user_id, connection.model_name)
    status, error_type = "success", None
    try:
        return answer_question(body.question, db, user_id, trace=trace)
    except Exception as exc:
        status, error_type = "error", type(exc).__name__
        raise
    finally:
        trace.finish(status, error_type)


@router.post("/analyze")
def analyze(body: SelectedNoteInput, db: Db, user_id: UserId) -> dict:
    note = current_note(body.note_id, user_id)
    row = require_connection(db, user_id)
    key, model_name = decrypt_key(row), row.model_name
    check_limit(user_id, "assistant", limit=10)
    evidence = Evidence(user_id)
    trace = TraceRecorder("analyze", user_id, model_name)
    agent = build_agent(chat_model(key, model_name), evidence,
        load_prompt("note_analysis_system.txt"), can_search=False)
    status, error_type = "success", None
    try:
        payload = parse_json_response(invoke(
            agent,
            load_prompt("note_analysis_request.txt", note_id=str(note.id)),
            trace=trace,
        ))
        trace.record_evidence(evidence)
        analysis_text = payload.get("analysis")
        suggestions = payload.get("suggestions")
        if not isinstance(analysis_text, str) or not isinstance(suggestions, list) or not all(isinstance(item, str) for item in suggestions):
            raise HTTPException(status_code=502, detail="模型输出格式无效，请重试")
        citations = evidence.verified(analysis_text + "\n" + "\n".join(suggestions))
        if not citations:
            raise HTTPException(status_code=502, detail="模型未提供可核对的原文引用，请重试")
        return {"analysis": analysis_text, "suggestions": suggestions[:6], "citations": citations}
    except Exception as exc:
        status, error_type = "error", type(exc).__name__
        raise
    finally:
        trace.finish(status, error_type)


@router.post("/classify")
def classify(body: SelectedNoteInput, db: Db, user_id: UserId) -> dict:
    note = current_note(body.note_id, user_id)
    row = require_connection(db, user_id)
    key, model_name = decrypt_key(row), row.model_name
    check_limit(user_id, "assistant", limit=10)
    notebooks = db.scalars(select(Notebook).where(Notebook.user_id == user_id, Notebook.deleted_at.is_(None))).all()
    tags = db.scalars(select(Tag).where(Tag.user_id == user_id, Tag.deleted_at.is_(None))).all()
    notebook_ids = {str(item.id) for item in notebooks}
    tag_ids = {str(item.id) for item in tags}
    evidence = Evidence(user_id)
    trace = TraceRecorder("classify", user_id, model_name)
    agent = build_agent(chat_model(key, model_name), evidence,
        load_prompt("note_classification_system.txt"), can_search=False)
    prompt = json.dumps({
        "note_id": str(note.id),
        "notebooks": [{"id": str(item.id), "name": item.name} for item in notebooks],
        "tags": [{"id": str(item.id), "name": item.name} for item in tags],
    }, ensure_ascii=False)
    status, error_type = "success", None
    try:
        payload = parse_json_response(invoke(agent, prompt, trace=trace))
        trace.record_evidence(evidence)
        proposed_notebook = payload.get("notebook_id")
        proposed_tags = payload.get("tag_ids")
        reason = payload.get("reason")
        if proposed_notebook is not None and (not isinstance(proposed_notebook, str) or proposed_notebook not in notebook_ids):
            raise HTTPException(status_code=502, detail="模型提出了无效的笔记本，请重试")
        if not isinstance(proposed_tags, list) or len(proposed_tags) > 20 or any(not isinstance(item, str) or item not in tag_ids for item in proposed_tags):
            raise HTTPException(status_code=502, detail="模型提出了无效的标签，请重试")
        if not isinstance(reason, str) or not evidence.verified(reason):
            raise HTTPException(status_code=502, detail="模型未提供可核对的分类依据，请重试")
        current = current_note(note.id, user_id)
        if current.version != note.version:
            raise HTTPException(status_code=409, detail="笔记已有新版本，请重试")
        return {
            "note_id": str(note.id), "note_version": note.version,
            "notebook_id": proposed_notebook, "tag_ids": list(dict.fromkeys(proposed_tags)),
            "reason": reason,
        }
    except Exception as exc:
        status, error_type = "error", type(exc).__name__
        raise
    finally:
        trace.finish(status, error_type)
