"""Image description, provider-agnostic.

- provider=ollama（默认）：Ollama 原生 ``/api/chat``，图片走 ``images`` 字节数组。
- provider=openai：OpenAI 兼容 ``/v1/chat/completions``，图片走 ``image_url`` data URI。

本地开发默认 Ollama；生产用第三方视觉模型（如百炼 qwen-vl-plus）。
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
import uuid

import httpx
from PIL import Image, ImageOps

from app.core.rate_limit import check_limit
from app.core.ollama_gate import ollama_inference_slot
from app.core.model_providers import vision_backend, chat_endpoint
from app.prompts import load_prompt

log = logging.getLogger(__name__)


def _prepare_image(image_bytes: bytes) -> tuple[bytes, str]:
    """Normalize images to a compact size before sending to the vision model."""
    with Image.open(io.BytesIO(image_bytes)) as source:
        image = ImageOps.exif_transpose(source)
        if "A" in image.getbands():
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")
        image.thumbnail((896, 896), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=84, optimize=True)
        return output.getvalue(), "image/jpeg"


def _ollama_payload(model: str, instruction: str, image_b64: str) -> dict:
    return {
        "model": model,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0, "num_predict": 64},
        "messages": [{
            "role": "user",
            "content": instruction,
            "images": [image_b64],
        }],
    }


def _openai_payload(model: str, instruction: str, image_b64: str, media_type: str) -> dict:
    return {
        "model": model,
        "temperature": 0,
        "max_tokens": 256,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": instruction},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
            ],
        }],
    }


def _extract_content(provider: str, body: dict) -> str:
    if provider == "openai":
        return body["choices"][0]["message"]["content"]
    return body["message"]["content"]


def describe_image_bytes(image_bytes: bytes, media_type: str, db, user_id: uuid.UUID) -> dict[str, str]:
    del media_type  # 归一化后统一按 JPEG 发送。
    check_limit(user_id, "vision_recognition", limit=60, window=3600)
    prepared, prepared_media_type = _prepare_image(image_bytes)
    image_b64 = base64.b64encode(prepared).decode("ascii")
    instruction = load_prompt("vision_description.txt")

    backend = vision_backend()
    if backend.provider == "openai":
        payload = _openai_payload(backend.model, instruction, image_b64, prepared_media_type)
        url = chat_endpoint(backend.base_url)
        headers = {"Authorization": f"Bearer {backend.api_key}"}
    else:
        payload = _ollama_payload(backend.model, instruction, image_b64)
        url = f"{backend.base_url}/api/chat"
        headers = None

    started = time.monotonic()
    # A runner can be killed while memory is tight / a remote call can blip.
    # One retry gives the backend time to recover while successful pages remain unaffected.
    try:
        with ollama_inference_slot("vision", wait_timeout=300):
            with httpx.Client(timeout=httpx.Timeout(300, connect=8), follow_redirects=False) as client:
                for attempt in range(2):
                    try:
                        response = client.post(url, json=payload, headers=headers)
                        response.raise_for_status()
                        break
                    except httpx.HTTPError:
                        if attempt == 1:
                            raise
                        log.warning("vision_retry provider=%s model=%s attempt=2", backend.provider, backend.model)
                        time.sleep(3)
        content = _extract_content(backend.provider, response.json())
        match = re.search(r"\{[\s\S]*\}", content)
        result = json.loads(match.group(0)) if match else {}
        caption = str(result.get("caption", "")).strip()
        if not caption:
            return {"caption": "", "status": "empty"}
        log.info(
            "model_inference_complete operation=vision provider=%s elapsed_ms=%s",
            backend.provider, round((time.monotonic() - started) * 1000),
        )
        return {"caption": caption[:500], "status": "ready"}
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        log.warning(
            "model_inference_failed operation=vision provider=%s model=%s elapsed_ms=%s",
            backend.provider, backend.model, round((time.monotonic() - started) * 1000),
        )
        raise RuntimeError("vision model is unavailable") from None
