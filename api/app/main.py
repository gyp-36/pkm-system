"""M1 API with independent core and embedding health status."""

import os

import httpx
from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from app.db import engine
from app.auth import router as auth_router
from app.notes import router as notes_router
from app.model_connection import router as connection_router
from app.assistant import router as assistant_router
from app.conversations import router as conversations_router
from app.search import router as search_router
from app.taxonomy import router as taxonomy_router


app = FastAPI(
    title="Personal Knowledge Management API",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    redoc_url=None,
)

app.include_router(auth_router)
app.include_router(taxonomy_router)
app.include_router(notes_router)
app.include_router(search_router)
app.include_router(connection_router)
app.include_router(assistant_router)
app.include_router(conversations_router)


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
