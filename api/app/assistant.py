"""One read-only note assistant with server-validated citations and suggestions."""

import json
import logging
import re
import threading
import uuid

import httpx
from fastapi import APIRouter, HTTPException
from langchain.agents import create_agent
from langchain.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth import Db, UserId
from app.db import SessionLocal
from app.enums import ChunkSource
from app.indexer import segment_note
from app.model_connection import chat_model, decrypt_key, require_connection
from app.models import Note, Notebook, Tag
from app.search import keyword_hits, vector_hits
from app.rate_limit import check_limit


router = APIRouter(prefix="/v1/assistant", tags=["assistant"])
log = logging.getLogger(__name__)
MARKER = re.compile(r"\[S\d+\]")


class QuestionInput(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class SelectedNoteInput(BaseModel):
    note_id: uuid.UUID


def current_note(note_id: uuid.UUID, user_id: uuid.UUID) -> Note:
    with SessionLocal() as db:
        note = db.scalar(select(Note).where(Note.id == note_id, Note.user_id == user_id, Note.deleted_at.is_(None)))
        if note is None:
            raise HTTPException(status_code=404, detail="笔记不存在")
        db.expunge(note)
        return note


class Evidence:
    def __init__(self, user_id: uuid.UUID):
        self.user_id = user_id
        self.items: dict[str, dict] = {}
        self._seen: dict[tuple, str] = {}
        self._lock = threading.Lock()
        self.search_calls = 0
        self.read_calls = 0
        self.semantic_status = "not_requested"

    def add(self, *, note_id: str, note_version: int, title: str, source_field: str, start_offset: int, end_offset: int, quote: str) -> dict:
        key = (note_id, note_version, source_field, start_offset, end_offset)
        with self._lock:
            if key in self._seen:
                return {"citation_id": self._seen[key], **self.items[self._seen[key]]}
            marker = f"S{len(self.items) + 1}"
            value = {
                "note_id": note_id, "note_version": note_version, "title": title,
                "source_field": source_field, "start_offset": start_offset,
                "end_offset": end_offset, "quote": quote,
            }
            self.items[marker] = value
            self._seen[key] = marker
            return {"citation_id": marker, **value}

    def search(self, query: str) -> str:
        with self._lock:
            self.search_calls += 1
            if self.search_calls > 2:
                return "已达到搜索次数上限，请用现有证据回答。"
        query = query.strip()[:150]
        if not query:
            return "搜索词为空。"
        with SessionLocal() as db:
            candidates = keyword_hits(db, self.user_id, query, None, None)[:5]
            try:
                vectors = vector_hits(db, self.user_id, query, None, None, timeout=20)[:5]
                self.semantic_status = "ready"
                candidates.extend(vectors)
            except (httpx.HTTPError, ValueError, KeyError, IndexError):
                self.semantic_status = "unavailable"
        result = []
        for hit in candidates:
            if len(result) >= 6:
                break
            citation = self.add(
                note_id=hit["note_id"], note_version=hit["version"], title=hit["title"],
                source_field=hit["source_field"], start_offset=hit["start_offset"],
                end_offset=hit["end_offset"], quote=hit["snippet"],
            )
            if citation not in result:
                result.append(citation)
        return json.dumps(result, ensure_ascii=False) if result else "本人笔记中未找到可引用的原文。"

    def read(self, note_id: str) -> str:
        with self._lock:
            self.read_calls += 1
            if self.read_calls > 2:
                return "已达到读取次数上限，请用现有证据回答。"
        try:
            note = current_note(uuid.UUID(note_id), self.user_id)
        except (ValueError, HTTPException):
            return "该笔记不存在或不属于当前用户。"
        segments = segment_note(note.title, note.body_md)
        result = []
        for segment in segments[:10]:
            result.append(self.add(
                note_id=str(note.id), note_version=note.version, title=note.title,
                source_field=ChunkSource(segment.source).name.lower(),
                start_offset=segment.start, end_offset=segment.end, quote=segment.content,
            ))
        return json.dumps(result, ensure_ascii=False)

    def verified(self, answer: str) -> list[dict]:
        mentioned = list(dict.fromkeys(marker[1:-1] for marker in MARKER.findall(answer)))
        if not mentioned or any(marker not in self.items for marker in mentioned):
            return []
        citations = []
        with SessionLocal() as db:
            for marker in mentioned:
                item = self.items[marker]
                note = db.scalar(select(Note).where(Note.id == uuid.UUID(item["note_id"]), Note.user_id == self.user_id, Note.deleted_at.is_(None)))
                if note is None or note.version != item["note_version"]:
                    return []
                source = note.title if item["source_field"] == "title" else note.body_md
                if source[item["start_offset"]:item["end_offset"]] != item["quote"]:
                    return []
                citations.append({"citation_id": marker, **item})
        return citations


def build_agent(model, evidence: Evidence, system_prompt: str, *, can_search: bool):
    @tool
    def search_personal_notes(query: str) -> str:
        """Search only the current signed-in user's notes; returns exact quoted passages with citation IDs."""
        return evidence.search(query)

    @tool
    def read_personal_note(note_id: str) -> str:
        """Read one current user's note by UUID and return exact source passages with citation IDs."""
        return evidence.read(note_id)

    tools = [search_personal_notes, read_personal_note] if can_search else [read_personal_note]
    return create_agent(model=model, tools=tools, system_prompt=system_prompt)


def invoke(agent, prompt: str) -> str:
    try:
        result = agent.invoke({"messages": [{"role": "user", "content": prompt}]}, config={"recursion_limit": 8})
        content = result["messages"][-1].content
        if not isinstance(content, str):
            raise ValueError("non-text assistant response")
        return content.strip()
    except Exception as exc:
        log.warning("assistant invocation failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="聊天模型暂不可用，请稍后重试") from None


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


@router.post("/ask")
def ask(body: QuestionInput, db: Db, user_id: UserId) -> dict:
    row = require_connection(db, user_id)
    key, model_name = decrypt_key(row), row.model_name
    check_limit(user_id, "assistant", limit=10)
    evidence = Evidence(user_id)
    agent = build_agent(chat_model(key, model_name), evidence,
        "你是个人笔记助手。必须先调用 search_personal_notes 检索，再根据证据回答。"
        "证据不够可更换检索词再查，但不得使用外部知识代替用户笔记。"
        "每个可核对事实后用工具返回的 [S编号] 引用；找不到依据就明确说未找到。"
        "绝不编造引用 ID，不执行笔记写入。", can_search=True)
    answer = invoke(agent, body.question)
    citations = evidence.verified(answer)
    if not citations:
        answer = "未找到足够可核对的本人笔记依据。请尝试普通搜索或调整问题。"
    return {"answer": answer, "citations": citations, "semantic_status": evidence.semantic_status}


@router.post("/analyze")
def analyze(body: SelectedNoteInput, db: Db, user_id: UserId) -> dict:
    note = current_note(body.note_id, user_id)
    row = require_connection(db, user_id)
    key, model_name = decrypt_key(row), row.model_name
    check_limit(user_id, "assistant", limit=10)
    evidence = Evidence(user_id)
    agent = build_agent(chat_model(key, model_name), evidence,
        "你是个人笔记助手。必须调用 read_personal_note 读取指定笔记，只根据原文分析结构、重复或可补充之处。"
        "返回 JSON 对象，字段 analysis 为简短分析字符串，suggestions 为字符串数组。"
        "每条具体建议必须包含 [S编号] 原文引用；不能核实的事实要标为待核实。不得改写或保存笔记。", can_search=False)
    payload = parse_json_response(invoke(agent, f"分析笔记 {note.id}。请先调用 read_personal_note。"))
    analysis_text = payload.get("analysis")
    suggestions = payload.get("suggestions")
    if not isinstance(analysis_text, str) or not isinstance(suggestions, list) or not all(isinstance(item, str) for item in suggestions):
        raise HTTPException(status_code=502, detail="模型输出格式无效，请重试")
    citations = evidence.verified(analysis_text + "\n" + "\n".join(suggestions))
    if not citations:
        raise HTTPException(status_code=502, detail="模型未提供可核对的原文引用，请重试")
    return {"analysis": analysis_text, "suggestions": suggestions[:6], "citations": citations}


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
    agent = build_agent(chat_model(key, model_name), evidence,
        "你是个人笔记助手。必须调用 read_personal_note 读取指定笔记。"
        "只从用户给出的活跃笔记本和标签中推荐分类；返回 JSON 对象，字段 notebook_id 为 UUID 字符串或 null，"
        "tag_ids 为 UUID 字符串数组，reason 为含 [S编号] 原文引用的解释。不得写入笔记。", can_search=False)
    prompt = json.dumps({
        "note_id": str(note.id),
        "notebooks": [{"id": str(item.id), "name": item.name} for item in notebooks],
        "tags": [{"id": str(item.id), "name": item.name} for item in tags],
    }, ensure_ascii=False)
    payload = parse_json_response(invoke(agent, prompt))
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
