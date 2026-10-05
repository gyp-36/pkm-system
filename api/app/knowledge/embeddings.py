"""Ollama's native batch embedding API, with schema dimension validation."""

import os
import logging
import time

import httpx

from app.core.ollama_gate import ollama_inference_slot


MODEL = os.getenv("EMBEDDING_MODEL", "qwen3-embedding:0.6b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
DIMENSIONS = 1024
log = logging.getLogger(__name__)


def embed(texts: list[str], *, timeout: float = 180.0) -> list[list[float]]:
    if not texts:
        return []
    started = time.monotonic()
    try:
        with ollama_inference_slot("embedding", wait_timeout=timeout):
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    f"{OLLAMA_URL}/api/embed",
                    json={"model": MODEL, "input": texts, "truncate": False},
                )
                response.raise_for_status()
                vectors = response.json()["embeddings"]
    except Exception as exc:
        log.warning(
            "ollama_inference_failed operation=embedding batch_size=%s error=%s",
            len(texts), type(exc).__name__,
        )
        raise
    log.info(
        "ollama_inference_complete operation=embedding batch_size=%s elapsed_ms=%s",
        len(texts), round((time.monotonic() - started) * 1000),
    )
    if len(vectors) != len(texts) or any(len(vector) != DIMENSIONS for vector in vectors):
        raise ValueError("Embedding 输出维度或数量不符合数据库约束")
    return vectors
