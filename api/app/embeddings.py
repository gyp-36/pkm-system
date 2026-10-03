"""Ollama's native batch embedding API, with schema dimension validation."""

import os

import httpx


MODEL = os.getenv("EMBEDDING_MODEL", "qwen3-embedding:0.6b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
DIMENSIONS = 1024


def embed(texts: list[str], *, timeout: float = 180.0) -> list[list[float]]:
    if not texts:
        return []
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": MODEL, "input": texts, "truncate": False},
        )
        response.raise_for_status()
        vectors = response.json()["embeddings"]
    if len(vectors) != len(texts) or any(len(vector) != DIMENSIONS for vector in vectors):
        raise ValueError("Embedding 输出维度或数量不符合数据库约束")
    return vectors
