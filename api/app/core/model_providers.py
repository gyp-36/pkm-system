"""Model provider resolution for embeddings and vision.

本地开发默认走同机 Ollama（``EMBEDDING_PROVIDER`` / ``VISION_PROVIDER`` 均为 ``ollama``），
行为与旧代码完全一致。生产可切到任意 OpenAI 兼容服务（如阿里云百炼 DashScope 兼容模式），
从而在低配服务器上彻底去掉 Ollama，释放全部常驻内存。

切换只需环境变量：
    EMBEDDING_PROVIDER=openai
    EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
    EMBEDDING_MODEL=text-embedding-v3
    EMBEDDING_API_KEY=sk-xxx
    VISION_PROVIDER=openai
    VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
    VISION_MODEL=qwen-vl-plus
    VISION_API_KEY=sk-xxx           # 省略则复用 EMBEDDING_API_KEY
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

Provider = Literal["ollama", "openai"]

OLLAMA_DEFAULT_URL = "http://ollama:11434"

_EMBEDDING_DIMENSIONS = 1024
_OPENAI_EMBED_MAX_BATCH = 10


@dataclass(frozen=True)
class Backend:
    provider: Provider
    model: str
    base_url: str
    api_key: str | None


def _provider(name: str, default: str = "ollama") -> Provider:
    value = (os.getenv(name) or default).strip().lower()
    if value not in ("ollama", "openai"):
        raise RuntimeError(f"{name} 只支持 ollama 或 openai，当前为 {value!r}")
    return value  # type: ignore[return-value]


def _chat_endpoint(base: str) -> str:
    """OpenAI 端点容错：允许填到 .../v1 或 .../v1/chat/completions 任一粒度。"""
    trimmed = base.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return f"{trimmed}/chat/completions"


def embedding_backend() -> Backend:
    provider = _provider("EMBEDDING_PROVIDER")
    model = os.getenv("EMBEDDING_MODEL", "qwen3-embedding:0.6b")
    if provider == "ollama":
        return Backend(provider, model, os.getenv("OLLAMA_URL", OLLAMA_DEFAULT_URL).rstrip("/"), None)
    base = (os.getenv("EMBEDDING_BASE_URL") or "").rstrip("/")
    key = os.getenv("EMBEDDING_API_KEY")
    if not base or not key:
        raise RuntimeError("EMBEDDING_PROVIDER=openai 时必须配置 EMBEDDING_BASE_URL 与 EMBEDDING_API_KEY")
    return Backend(provider, model, base, key)


def vision_backend() -> Backend:
    provider = _provider("VISION_PROVIDER")
    model = os.getenv("VISION_MODEL", "qwen3-vl:2b-instruct")
    if provider == "ollama":
        return Backend(provider, model, os.getenv("OLLAMA_URL", OLLAMA_DEFAULT_URL).rstrip("/"), None)
    base = (os.getenv("VISION_BASE_URL") or os.getenv("EMBEDDING_BASE_URL") or "").rstrip("/")
    key = os.getenv("VISION_API_KEY") or os.getenv("EMBEDDING_API_KEY")
    if not base or not key:
        raise RuntimeError("VISION_PROVIDER=openai 时必须配置 VISION_BASE_URL/VISION_API_KEY（或复用 EMBEDDING_*）")
    return Backend(provider, model, base, key)


def embedding_dimensions() -> int:
    return _EMBEDDING_DIMENSIONS


def openai_embed_max_batch() -> int:
    return _OPENAI_EMBED_MAX_BATCH


def chat_endpoint(base: str) -> str:
    return _chat_endpoint(base)
