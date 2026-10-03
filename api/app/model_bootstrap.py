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
OLLAMA = os.environ.get("OLLAMA_URL", "http://ollama:11434")
REGISTRY = "https://registry.ollama.ai/v2/library/qwen3-embedding"

if MODEL != "qwen3-embedding:0.6b":
    raise SystemExit(f"Unexpected bootstrap model: {MODEL}")


def installed(client: httpx.Client) -> bool:
    response = client.get(f"{OLLAMA}/api/tags")
    response.raise_for_status()
    return MODEL in {item.get("name") for item in response.json().get("models", [])}


def pull(client: httpx.Client) -> None:
    response = client.post(f"{OLLAMA}/api/pull", json={"model": MODEL, "stream": False}, timeout=900)
    response.raise_for_status()
    if response.json().get("status") != "success":
        raise RuntimeError(f"Ollama pull did not report success: {response.text[:300]}")


def stage_blob(client: httpx.Client, digest: str) -> None:
    check = client.head(f"{OLLAMA}/api/blobs/{digest}")
    if check.status_code == 200:
        return
    if check.status_code != 404:
        check.raise_for_status()

    with tempfile.TemporaryDirectory(prefix="pkm-model-") as directory:
        path = Path(directory) / "model.blob"
        checksum = hashlib.sha256()
        with client.stream("GET", f"{REGISTRY}/blobs/{digest}", timeout=900) as response:
            response.raise_for_status()
            with path.open("wb") as target:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    target.write(chunk)
                    checksum.update(chunk)
        if f"sha256:{checksum.hexdigest()}" != digest:
            raise RuntimeError(f"Registry blob checksum mismatch: {digest}")
        print(f"Verified official blob {digest} ({path.stat().st_size} bytes)", flush=True)
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
        if installed(client):
            print(f"{MODEL} already installed", flush=True)
            return
        try:
            pull(client)
        except httpx.HTTPStatusError as error:
            if "redirect target not allowed" not in error.response.text:
                raise
            print("Ollama rejected a registry redirect; staging verified blobs via its API", flush=True)
            manifest = client.get(f"{REGISTRY}/manifests/0.6b", timeout=30)
            manifest.raise_for_status()
            data = manifest.json()
            for entry in [data["config"], *data["layers"]]:
                stage_blob(client, entry["digest"])
            pull(client)
        if not installed(client):
            raise RuntimeError("Ollama pull finished without installing the model")
        print(f"{MODEL} installed", flush=True)


if __name__ == "__main__":
    main()

