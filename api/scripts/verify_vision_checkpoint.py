"""Verify that cached vision pages are skipped and failed pages are retried."""

from __future__ import annotations

import io
import uuid

from PIL import Image

from app.knowledge import ollama_vision
from app.knowledge.file_ingest import extract_file


buffer = io.BytesIO()
Image.new("RGB", (32, 32), "white").save(buffer, format="PNG")
content = buffer.getvalue()
user_id = uuid.uuid4()
original_describe = ollama_vision.describe_image_bytes

try:
    def unexpected_inference(*_args, **_kwargs):
        raise AssertionError("a cached successful page must not call Ollama")

    ollama_vision.describe_image_bytes = unexpected_inference
    cached_body, _, cached_status = extract_file(
        "png", content, None, user_id,
        vision_results={"1": {"caption": "已保存的页面描述", "status": "ready"}},
    )
    assert "已保存的页面描述" in cached_body and cached_status == "ready"

    checkpoints: list[tuple[int, str, str]] = []

    def recover_page(*_args, **_kwargs):
        return {"caption": "重试成功的页面描述", "status": "ready"}

    ollama_vision.describe_image_bytes = recover_page
    recovered_body, _, recovered_status = extract_file(
        "png", content, None, user_id,
        vision_results={"1": {"caption": "", "status": "failed"}},
        save_vision_result=lambda page, caption, status: checkpoints.append((page, caption, status)),
    )
    assert "重试成功的页面描述" in recovered_body and recovered_status == "ready"
    assert checkpoints == [(1, "重试成功的页面描述", "ready")]
finally:
    ollama_vision.describe_image_bytes = original_describe

print("vision checkpoint: cached page skipped; failed page retried and checkpointed")
