"""Run inside the API container to verify the model and pgvector round trip."""

import json
import os
import time

import httpx
from sqlalchemy import text

from app.core.db import engine


model = os.environ.get("EMBEDDING_MODEL", "qwen3-embedding:0.6b")
url = os.environ.get("OLLAMA_URL", "http://ollama:11434")
started = time.monotonic()
with httpx.Client(timeout=180.0) as client:
    response = client.post(
        f"{url}/api/embed",
        json={"model": model, "input": "这是一段用于验证个人笔记语义检索的中文文本。", "truncate": False},
    )
    response.raise_for_status()
    payload = response.json()
vector = payload["embeddings"][0]
elapsed = time.monotonic() - started
assert len(vector) == 1024, f"Expected 1024 dimensions, got {len(vector)}"
literal = json.dumps(vector, separators=(",", ":"))
with engine.begin() as connection:
    connection.execute(text("CREATE TEMP TABLE probe_vectors (embedding vector(1024))"))
    connection.execute(text("INSERT INTO probe_vectors (embedding) VALUES (CAST(:value AS vector))"), {"value": literal})
    distance = connection.execute(
        text("SELECT embedding <=> CAST(:value AS vector) FROM probe_vectors"), {"value": literal}
    ).scalar_one()
assert abs(distance) < 1e-5, distance
print(json.dumps({"model": model, "dimensions": len(vector), "wall_seconds": round(elapsed, 3), "self_cosine_distance": distance, "ollama_total_duration_ns": payload.get("total_duration")}, ensure_ascii=False))
