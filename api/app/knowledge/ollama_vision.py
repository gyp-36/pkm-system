"""Local Ollama-backed image description."""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import time
import uuid

import httpx
from PIL import Image, ImageOps

from app.core.rate_limit import check_limit
from app.core.ollama_gate import ollama_inference_slot
from app.prompts import load_prompt

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")
VISION_MODEL = os.getenv("VISION_MODEL", "qwen3-vl:2b-instruct")
log = logging.getLogger(__name__)


def _prepare_image(image_bytes: bytes) -> bytes:
    """Normalize images to a compact size for local CPU inference."""
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
        return output.getvalue()


def describe_image_bytes(image_bytes: bytes, media_type: str, db, user_id: uuid.UUID) -> dict[str, str]:
    del media_type  # Ollama 的聊天 API 接受原始 Base64 图像字节。
    check_limit(user_id, "vision_recognition", limit=60, window=3600)
    image_bytes = _prepare_image(image_bytes)
    payload = {
        "model": VISION_MODEL,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0, "num_predict": 64},
        "messages": [{
            "role": "user",
            "content": load_prompt("vision_description.txt"),
            "images": [base64.b64encode(image_bytes).decode("ascii")],
        }],
    }
    started = time.monotonic()
    # A runner can be killed while memory is tight. One retry gives Ollama time
    # to recreate it while successful pages remain unaffected.
    try:
        with ollama_inference_slot("vision", wait_timeout=300):
            with httpx.Client(timeout=httpx.Timeout(300, connect=8), follow_redirects=False) as client:
                for attempt in range(2):
                    try:
                        response = client.post(f"{OLLAMA_URL}/api/chat", json=payload)
                        response.raise_for_status()
                        break
                    except httpx.HTTPError:
                        if attempt == 1:
                            raise
                        log.warning("ollama_vision_retry model=%s attempt=2", VISION_MODEL)
                        time.sleep(3)
        content = response.json()["message"]["content"]
        match = re.search(r"\{[\s\S]*\}", content)
        result = json.loads(match.group(0)) if match else {}
        caption = str(result.get("caption", "")).strip()
        if not caption:
            return {"caption": "", "status": "empty"}
        log.info("ollama_inference_complete operation=vision elapsed_ms=%s", round((time.monotonic() - started) * 1000))
        return {"caption": caption[:500], "status": "ready"}
    except (httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        log.warning(
            "ollama_inference_failed operation=vision model=%s elapsed_ms=%s",
            VISION_MODEL, round((time.monotonic() - started) * 1000),
        )
        raise RuntimeError("local vision model is unavailable") from None
