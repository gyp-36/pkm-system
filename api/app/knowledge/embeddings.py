"""Batch embeddings, provider-agnostic.

- provider=ollama（默认）：走 Ollama 原生 ``/api/embed``。
- provider=openai：走 OpenAI 兼容 ``/v1/embeddings``（如百炼 DashScope），按供应商上限分批。

对外签名 ``embed(texts, *, timeout=...)`` 保持不变。
"""

import logging
import os
import time

import httpx

from app.core.ollama_gate import ollama_inference_slot
from app.core.model_providers import (
    embedding_backend,
    embedding_dimensions,
    openai_embed_max_batch,
)

DIMENSIONS = embedding_dimensions()
log = logging.getLogger(__name__)


def _embed_ollama(texts: list[str], backend, timeout: float) -> list[list[float]]:
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{backend.base_url}/api/embed",
            json={"model": backend.model, "input": texts, "truncate": False},
        )
        response.raise_for_status()
        return response.json()["embeddings"]


def _embed_openai(texts: list[str], backend, timeout: float) -> list[list[float]]:
    headers = {"Authorization": f"Bearer {backend.api_key}"}
    batch_size = openai_embed_max_batch()
    vectors: list[list[float]] = []
    with httpx.Client(timeout=timeout) as client:
        for start in range(0, len(texts), batch_size):
            chunk = texts[start : start + batch_size]
            response = client.post(
                f"{backend.base_url}/embeddings",
                headers=headers,
                json={
                    "model": backend.model,
                    "input": chunk,
                    "dimensions": DIMENSIONS,
                    "encoding_format": "float",
                },
            )
            response.raise_for_status()
            data = response.json()["data"]
            # 兼容接口应保持输入顺序，但按 index 显式排序以防万一。
            data.sort(key=lambda item: item.get("index", 0))
            vectors.extend(item["embedding"] for item in data)
    return vectors


def embed(texts: list[str], *, timeout: float = 180.0) -> list[list[float]]:
    if not texts:
        return []
    started = time.monotonic()
    backend = embedding_backend()
    try:
        with ollama_inference_slot("embedding", wait_timeout=timeout):
            if backend.provider == "openai":
                vectors = _embed_openai(texts, backend, timeout)
            else:
                vectors = _embed_ollama(texts, backend, timeout)
    except Exception as exc:
        log.warning(
            "model_inference_failed operation=embedding provider=%s batch_size=%s error=%s",
            backend.provider, len(texts), type(exc).__name__,
        )
        raise
    log.info(
        "model_inference_complete operation=embedding provider=%s batch_size=%s elapsed_ms=%s",
        backend.provider, len(texts), round((time.monotonic() - started) * 1000),
    )
    if len(vectors) != len(texts) or any(len(vector) != DIMENSIONS for vector in vectors):
        raise ValueError("Embedding 输出维度或数量不符合数据库约束")
    return vectors
