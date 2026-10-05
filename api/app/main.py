"""M1 API with independent core and embedding health status."""

import os
import time

import httpx
from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from app.core.db import engine
from app.auth.auth import router as auth_router
from app.knowledge.notes import router as notes_router
from app.assistant.model_connection import router as connection_router
from app.assistant.assistant import router as assistant_router
from app.assistant.conversations import router as conversations_router
from app.assistant.tracing import router as assistant_traces_router
from app.assistant.digests import router as digests_router
from app.knowledge.reminders import router as reminders_router, note_router as note_reminders_router, workbench_router
from app.knowledge.search import router as search_router
from app.knowledge.taxonomy import router as taxonomy_router
from app.knowledge.m3 import router as m3_router
from app.knowledge.upload_sessions import router as upload_sessions_router
from app.knowledge.archive import router as archive_router
from app.knowledge.templates import router as templates_router
from app.core.object_storage import ensure_bucket
from app.ops.audit_middleware import AuditAccessMiddleware


app = FastAPI(
    title="Personal Knowledge Management API",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    redoc_url=None,
)

# 请求层可观测性：注入 request_id 并记录全量访问日志（独立会话，失败也留痕）。
app.add_middleware(AuditAccessMiddleware)

app.include_router(auth_router)
app.include_router(taxonomy_router)
app.include_router(archive_router)
app.include_router(notes_router)
app.include_router(templates_router)
app.include_router(m3_router)
app.include_router(upload_sessions_router)
app.include_router(search_router)
app.include_router(connection_router)
app.include_router(assistant_router)
app.include_router(conversations_router)
app.include_router(assistant_traces_router)
app.include_router(digests_router)
app.include_router(reminders_router)
app.include_router(note_reminders_router)
app.include_router(workbench_router)


@app.on_event("startup")
def initialize_object_storage() -> None:
    last_error: Exception | None = None
    for attempt in range(20):
        try:
            ensure_bucket()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(min(0.5 + attempt * 0.25, 3))
    raise RuntimeError("object storage is unavailable") from last_error


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def ready() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM pkm_alembic_version LIMIT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ok", "database": "ready"}


@app.get("/health/embedding")
def embedding() -> dict[str, str]:
    model = os.environ.get("EMBEDDING_MODEL", "qwen3-embedding:0.6b")
    url = os.environ.get("OLLAMA_URL", "http://ollama:11434")
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{url}/api/tags")
            response.raise_for_status()
            names = {item.get("name") for item in response.json().get("models", [])}
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="embedding service unavailable") from exc
    if model not in names:
        raise HTTPException(status_code=503, detail="embedding model not installed")
    return {"status": "ok", "model": model}
