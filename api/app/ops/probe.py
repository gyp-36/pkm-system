"""Run inside the API container to verify the embedding model and pgvector round trip."""

import json
import time

from sqlalchemy import text

from app.core.db import engine
from app.core.model_providers import embedding_backend
from app.knowledge.embeddings import embed

backend = embedding_backend()
started = time.monotonic()
vector = embed(["这是一段用于验证个人笔记语义检索的中文文本。"], timeout=180.0)[0]
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
print(json.dumps({
    "provider": backend.provider,
    "model": backend.model,
    "dimensions": len(vector),
    "wall_seconds": round(elapsed, 3),
    "self_cosine_distance": distance,
}, ensure_ascii=False))
