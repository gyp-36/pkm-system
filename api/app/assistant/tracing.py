"""Local, redacted Agent execution traces for development environments."""

import logging
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from langchain_core.callbacks import BaseCallbackHandler
from sqlalchemy import func, select

from app.auth.auth import Db, UserId
from app.core.db import SessionLocal
from app.core.models import AssistantTrace
from app.contracts.tracing import TraceEnabledOut, TraceListOut, TraceOut


log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/dev/assistant-traces", tags=["developer assistant traces"])
RETENTION_DAYS = 30


def trace_view_enabled() -> bool:
    environment = os.getenv("APP_ENV", "").casefold()
    enabled = os.getenv("ASSISTANT_TRACE_VIEW_ENABLED", "false").casefold() in {"1", "true", "yes"}
    return environment in {"dev", "development", "local"} and enabled


def require_trace_view() -> None:
    if not trace_view_enabled():
        raise HTTPException(status_code=404, detail="Not found")


class TraceRecorder:
    """Collect small metadata events and persist them in an isolated DB session."""

    def __init__(
        self,
        entrypoint: str,
        user_id: uuid.UUID,
        model_name: str | None,
        conversation_id: uuid.UUID | None = None,
    ) -> None:
        self.id = uuid.uuid4()
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.started_at = datetime.now(timezone.utc)
        self.started_clock = time.perf_counter()
        self.steps: list[dict] = []
        self.active = trace_view_enabled()
        if not self.active:
            return
        try:
            with SessionLocal() as db:
                db.add(AssistantTrace(
                    id=self.id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    entrypoint=entrypoint,
                    model_name=model_name,
                    status="running",
                    started_at=self.started_at,
                    steps=[],
                ))
                db.commit()
        except Exception as exc:
            self.active = False
            log.warning("assistant trace start failed: %s", type(exc).__name__)

    def add_step(
        self,
        kind: str,
        name: str,
        *,
        status: str = "success",
        duration_ms: int | None = None,
        summary: dict | None = None,
    ) -> None:
        if not self.active:
            return
        self.steps.append({
            "index": len(self.steps) + 1,
            "kind": kind,
            "name": name[:80],
            "status": status[:16],
            "duration_ms": max(0, duration_ms) if duration_ms is not None else None,
            "summary": summary or {},
            "at": datetime.now(timezone.utc).isoformat(),
        })
        self._persist_steps()

    def record_model_message(self, message, duration_ms: int) -> None:
        tool_calls = getattr(message, "tool_calls", None) or []
        safe_calls = []
        for call in tool_calls[:12]:
            args = call.get("args", {}) if isinstance(call, dict) else {}
            safe_calls.append({
                "name": str(call.get("name", "tool"))[:80] if isinstance(call, dict) else "tool",
                "argument_fields": sorted(str(key)[:80] for key in args)[:20] if isinstance(args, dict) else [],
            })
        usage = getattr(message, "usage_metadata", None)
        metadata = getattr(message, "response_metadata", {}) or {}
        finish_reason = metadata.get("finish_reason")
        safe_usage = {}
        if isinstance(usage, dict):
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, int):
                    safe_usage[key] = value
        content = getattr(message, "content", "")
        if isinstance(content, str):
            output_characters = len(content)
        elif isinstance(content, list):
            output_characters = sum(len(block.get("text", "")) for block in content if isinstance(block, dict) and isinstance(block.get("text"), str))
        else:
            output_characters = 0
        self.add_step(
            "model",
            "模型调用",
            duration_ms=duration_ms,
            summary={
                "tool_calls": safe_calls,
                "output_characters": output_characters,
                "usage": safe_usage,
                "finish_reason": finish_reason if finish_reason in {"stop", "length", "tool_calls", "content_filter"} else None,
            },
        )

    def record_tool_message(self, message, duration_ms: int) -> None:
        content = getattr(message, "content", "")
        output_characters = len(content) if isinstance(content, str) else 0
        status = getattr(message, "status", "success")
        self.add_step(
            "tool",
            str(getattr(message, "name", "工具调用")),
            status="error" if status == "error" else "success",
            duration_ms=duration_ms,
            summary={"output_characters": output_characters},
        )

    def update_step(self, index: int, *, status: str, duration_ms: int, summary: dict) -> None:
        if not self.active:
            return
        for step in self.steps:
            if step["index"] == index:
                step["status"] = status[:16]
                step["duration_ms"] = max(0, duration_ms)
                step["summary"] = {**step.get("summary", {}), **summary}
                step["finished_at"] = datetime.now(timezone.utc).isoformat()
                self._persist_steps()
                return

    def record_evidence(self, evidence) -> None:
        if evidence is None:
            return
        self.add_step(
            "retrieval",
            "检索汇总",
            summary={
                "search_calls": int(getattr(evidence, "search_calls", 0)),
                "read_calls": int(getattr(evidence, "read_calls", 0)),
                "evidence_count": len(getattr(evidence, "items", {})),
                "semantic_status": str(getattr(evidence, "semantic_status", "unknown")),
            },
        )

    def set_assistant_message(self, message_id: uuid.UUID | str | None) -> None:
        if not self.active or message_id is None:
            return
        try:
            with SessionLocal() as db:
                trace = db.get(AssistantTrace, self.id)
                if trace is not None:
                    trace.assistant_message_id = uuid.UUID(str(message_id))
                    db.commit()
        except Exception as exc:
            log.warning("assistant trace message link failed: %s", type(exc).__name__)

    def set_model_name(self, model_name: str | None) -> None:
        if not self.active or not model_name:
            return
        try:
            with SessionLocal() as db:
                trace = db.get(AssistantTrace, self.id)
                if trace is not None:
                    trace.model_name = model_name[:120]
                    db.commit()
        except Exception as exc:
            log.warning("assistant trace model link failed: %s", type(exc).__name__)

    def finish(self, status: str, error_type: str | None = None) -> None:
        if not self.active:
            return
        finished_at = datetime.now(timezone.utc)
        try:
            with SessionLocal() as db:
                trace = db.get(AssistantTrace, self.id)
                if trace is not None:
                    trace.steps = self.steps
                    trace.status = status
                    trace.error_type = error_type[:120] if error_type else None
                    trace.finished_at = finished_at
                    trace.duration_ms = max(0, int((time.perf_counter() - self.started_clock) * 1000))
                    db.commit()
        except Exception as exc:
            log.warning("assistant trace finish failed: %s", type(exc).__name__)

    def _persist_steps(self) -> None:
        try:
            with SessionLocal() as db:
                trace = db.get(AssistantTrace, self.id)
                if trace is not None:
                    trace.steps = self.steps
                    db.commit()
        except Exception as exc:
            # Disable further writes after a storage failure; the Agent request proceeds.
            self.active = False
            log.warning("assistant trace step save failed: %s", type(exc).__name__)

    def callback_handler(self):
        return TraceCallbackHandler(self) if self.active else None


class TraceCallbackHandler(BaseCallbackHandler):
    """Capture callback boundaries without retaining prompt/tool content."""

    def __init__(self, recorder: TraceRecorder) -> None:
        super().__init__()
        self.recorder = recorder
        self.started: dict[str, float] = {}
        self.tool_names: dict[str, str] = {}
        self.tool_steps: dict[str, int] = {}

    @staticmethod
    def _run_key(kwargs: dict) -> str:
        return str(kwargs.get("run_id", uuid.uuid4()))

    def on_chat_model_start(self, serialized: dict, messages: list, **kwargs) -> None:
        self.started[self._run_key(kwargs)] = time.perf_counter()

    def on_llm_end(self, response, **kwargs) -> None:
        key = self._run_key(kwargs)
        duration = int((time.perf_counter() - self.started.pop(key, time.perf_counter())) * 1000)
        generations = getattr(response, "generations", []) or []
        generation = generations[0][0] if generations and generations[0] else None
        message = getattr(generation, "message", None)
        if message is not None:
            self.recorder.record_model_message(message, duration)
            return
        output = getattr(generation, "text", "") if generation is not None else ""
        self.recorder.add_step("model", "模型调用", duration_ms=duration, summary={"output_characters": len(output) if isinstance(output, str) else 0})

    def on_llm_error(self, error: BaseException, **kwargs) -> None:
        key = self._run_key(kwargs)
        duration = int((time.perf_counter() - self.started.pop(key, time.perf_counter())) * 1000)
        self.recorder.add_step("error", "模型调用失败", status="error", duration_ms=duration, summary={"error_type": type(error).__name__})

    def on_tool_start(self, serialized: dict, input_str: str, **kwargs) -> None:
        key = self._run_key(kwargs)
        self.started[key] = time.perf_counter()
        self.tool_names[key] = str(serialized.get("name") or "工具调用")[:80]
        try:
            parsed = json.loads(input_str)
        except (TypeError, ValueError):
            parsed = None
        self.recorder.add_step(
            "tool",
            self.tool_names[key],
            status="running",
            summary={"argument_fields": sorted(str(field)[:80] for field in parsed)[:20] if isinstance(parsed, dict) else []},
        )
        if self.recorder.steps:
            self.tool_steps[key] = self.recorder.steps[-1]["index"]

    def on_tool_end(self, output, **kwargs) -> None:
        key = self._run_key(kwargs)
        duration = int((time.perf_counter() - self.started.pop(key, time.perf_counter())) * 1000)
        text = output if isinstance(output, str) else getattr(output, "content", "")
        name = self.tool_names.pop(key, "工具调用")
        summary = {"output_characters": len(text) if isinstance(text, str) else 0}
        index = self.tool_steps.pop(key, None)
        if index is not None:
            self.recorder.update_step(index, status="success", duration_ms=duration, summary=summary)
        else:
            self.recorder.add_step("tool", name, duration_ms=duration, summary=summary)

    def on_tool_error(self, error: BaseException, **kwargs) -> None:
        key = self._run_key(kwargs)
        duration = int((time.perf_counter() - self.started.pop(key, time.perf_counter())) * 1000)
        name = self.tool_names.pop(key, "工具调用")
        index = self.tool_steps.pop(key, None)
        summary = {"error_type": type(error).__name__}
        if index is not None:
            self.recorder.update_step(index, status="error", duration_ms=duration, summary=summary)
        else:
            self.recorder.add_step("tool", name, status="error", duration_ms=duration, summary=summary)


def trace_json(trace: AssistantTrace) -> dict:
    return {
        "id": str(trace.id),
        "user_id": str(trace.user_id),
        "conversation_id": str(trace.conversation_id) if trace.conversation_id else None,
        "assistant_message_id": str(trace.assistant_message_id) if trace.assistant_message_id else None,
        "entrypoint": trace.entrypoint,
        "model_name": trace.model_name,
        "status": trace.status,
        "error_type": trace.error_type,
        "started_at": trace.started_at.isoformat(),
        "finished_at": trace.finished_at.isoformat() if trace.finished_at else None,
        "duration_ms": trace.duration_ms,
        "steps": trace.steps,
    }


@router.get("/enabled", response_model=TraceEnabledOut)
def get_trace_view_status(_user_id: UserId) -> dict:
    return {"enabled": trace_view_enabled()}


@router.get("", response_model=TraceListOut)
def list_traces(
    user_id: UserId,
    db: Db,
    entrypoint: str | None = Query(default=None, max_length=32),
    status: str | None = Query(default=None, max_length=16),
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> dict:
    require_trace_view()
    query = select(AssistantTrace).where(AssistantTrace.user_id == user_id)
    if entrypoint:
        query = query.where(AssistantTrace.entrypoint == entrypoint)
    if status:
        query = query.where(AssistantTrace.status == status)
    if started_from:
        query = query.where(AssistantTrace.started_at >= started_from)
    if started_to:
        query = query.where(AssistantTrace.started_at <= started_to)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(query.order_by(AssistantTrace.started_at.desc(), AssistantTrace.id.desc()).offset(offset).limit(limit)).all()
    return {"items": [trace_json(item) for item in items], "total": total, "limit": limit, "offset": offset}


@router.get("/by-message/{assistant_message_id}", response_model=TraceOut)
def trace_for_message(assistant_message_id: uuid.UUID, user_id: UserId, db: Db) -> dict:
    require_trace_view()
    trace = db.scalar(select(AssistantTrace).where(
        AssistantTrace.assistant_message_id == assistant_message_id,
        AssistantTrace.user_id == user_id,
    ))
    if trace is None:
        raise HTTPException(status_code=404, detail="调用链不存在")
    return trace_json(trace)


@router.get("/{trace_id}", response_model=TraceOut)
def get_trace(trace_id: uuid.UUID, user_id: UserId, db: Db) -> dict:
    require_trace_view()
    trace = db.scalar(select(AssistantTrace).where(
        AssistantTrace.id == trace_id,
        AssistantTrace.user_id == user_id,
    ))
    if trace is None:
        raise HTTPException(status_code=404, detail="调用链不存在")
    return trace_json(trace)


def cleanup_expired_traces(now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=RETENTION_DAYS)
    try:
        with SessionLocal() as db:
            result = db.query(AssistantTrace).filter(AssistantTrace.started_at < cutoff).delete(synchronize_session=False)
            db.commit()
            return int(result or 0)
    except Exception as exc:
        log.warning("assistant trace cleanup failed: %s", type(exc).__name__)
        return 0
