"""Install the official model, including a network redirect fallback.

Some networks resolve object-storage redirects to reserved gateway addresses.
Ollama rejects those redirects. The fallback downloads each digest from the
official registry, verifies it, pushes it through Ollama's documented blob API,
then lets Ollama register the official manifest with its pull endpoint.
"""

import hashlib
import os
import tempfile
from pathlib import Path

import httpx


MODEL = os.environ.get("EMBEDDING_MODEL", "qwen3-embedding:0.6b")
VISION_MODEL = os.environ.get("VISION_MODEL", "qwen3-vl:2b-instruct")
OLLAMA = os.environ.get("OLLAMA_URL", "http://ollama:11434")

if MODEL != "qwen3-embedding:0.6b":
    raise SystemExit(f"Unexpected bootstrap model: {MODEL}")


def installed(client: httpx.Client, model: str) -> bool:
    response = client.get(f"{OLLAMA}/api/tags")
    response.raise_for_status()
    return model in {item.get("name") for item in response.json().get("models", [])}


def pull(client: httpx.Client, model: str) -> None:
    try:
        response = client.post(f"{OLLAMA}/api/pull", json={"model": model, "stream": False}, timeout=1800)
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        if "redirect target not allowed" not in error.response.text:
            raise
        model_name, _, tag = model.rpartition(":")
        if not model_name:
            model_name, tag = model, "latest"
        registry_path = model_name if "/" in model_name else f"library/{model_name}"
        registry = f"https://registry.ollama.ai/v2/{registry_path}"
        print(f"Ollama 拒绝了模型 {model} 的仓库重定向；正在暂存已校验的数据块", flush=True)
        manifest = client.get(f"{registry}/manifests/{tag or 'latest'}", timeout=30)
        manifest.raise_for_status()
        data = manifest.json()
        for entry in [data["config"], *data["layers"]]:
            stage_blob(client, registry, entry["digest"])
        response = client.post(f"{OLLAMA}/api/pull", json={"model": model, "stream": False}, timeout=1800)
        response.raise_for_status()
    response.raise_for_status()
    if response.json().get("status") != "success":
        raise RuntimeError(f"Ollama pull did not report success for {model}: {response.text[:300]}")


def stage_blob(client: httpx.Client, registry: str, digest: str) -> None:
    check = client.head(f"{OLLAMA}/api/blobs/{digest}")
    if check.status_code == 200:
        return
    if check.status_code != 404:
        check.raise_for_status()

    with tempfile.TemporaryDirectory(prefix="pkm-model-") as directory:
        path = Path(directory) / "model.blob"
        checksum = hashlib.sha256()
        with client.stream("GET", f"{registry}/blobs/{digest}", timeout=900) as response:
            response.raise_for_status()
            with path.open("wb") as target:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    target.write(chunk)
                    checksum.update(chunk)
        if f"sha256:{checksum.hexdigest()}" != digest:
            raise RuntimeError(f"Registry blob checksum mismatch: {digest}")
        print(f"已校验官方数据块 {digest}（{path.stat().st_size} 字节）", flush=True)
        with path.open("rb") as source:
            uploaded = client.post(
                f"{OLLAMA}/api/blobs/{digest}",
                content=source,
                headers={"Content-Type": "application/octet-stream"},
                timeout=900,
            )
        uploaded.raise_for_status()


def main() -> None:
    with httpx.Client(follow_redirects=True, timeout=30) as client:
        if not installed(client, MODEL):
            pull(client, MODEL)
            if not installed(client, MODEL):
                raise RuntimeError(f"Ollama pull finished without installing {MODEL}")
            print(f"{MODEL} 已安装", flush=True)
        else:
            print(f"{MODEL} 已安装，无需重复安装", flush=True)

        if not installed(client, VISION_MODEL):
            pull(client, VISION_MODEL)
            if not installed(client, VISION_MODEL):
                raise RuntimeError(f"Ollama pull finished without installing {VISION_MODEL}")
            print(f"{VISION_MODEL} 已安装", flush=True)
        else:
            print(f"{VISION_MODEL} 已安装，无需重复安装", flush=True)


if __name__ == "__main__":
    main()
