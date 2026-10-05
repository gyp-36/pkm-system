#!/usr/bin/env python3
"""Choose a free local web port, then start the entire app through Compose."""

from __future__ import annotations

import secrets
import base64
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.local"
PORTS = range(15173, 15274)
OBJECT_STORAGE_PORTS = range(19000, 19100)


def read_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    return dict(
        line.split("=", 1)
        for line in ENV_FILE.read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )


def free(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def existing_web_port() -> int | None:
    if not ENV_FILE.exists():
        return None
    result = subprocess.run(
        ["docker", "compose", "--env-file", str(ENV_FILE), "port", "web", "5173"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return None
    try:
        return int(result.stdout.strip().rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


def existing_service_port(service: str, internal_port: int) -> int | None:
    result = subprocess.run(
        ["docker", "compose", "--env-file", str(ENV_FILE), "port", service, str(internal_port)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return None
    try:
        return int(result.stdout.strip().rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


def main() -> int:
    if subprocess.run(["docker", "info"], capture_output=True, check=False).returncode:
        print("Docker 守护进程不可用，请先启动 Docker Desktop。", file=sys.stderr)
        return 1

    env = read_env()
    # 检查 Compose 端口时需要提供所有必需的插值变量。
    # 探测已运行的服务前，先补齐新增的对象存储密钥。
    env.update(
        APP_ENV=env.get("APP_ENV", "development"),
        ASSISTANT_TRACE_VIEW_ENABLED=env.get("ASSISTANT_TRACE_VIEW_ENABLED", "true"),
        OBJECT_STORAGE_ACCESS_KEY=env.get("OBJECT_STORAGE_ACCESS_KEY", secrets.token_hex(16).upper()),
        OBJECT_STORAGE_SECRET_KEY=env.get("OBJECT_STORAGE_SECRET_KEY", secrets.token_urlsafe(40)),
        POSTGRES_USER=env.get("POSTGRES_USER", "pkm"),
        POSTGRES_DB=env.get("POSTGRES_DB", "pkm"),
        POSTGRES_PASSWORD=env.get("POSTGRES_PASSWORD", secrets.token_hex(24)),
        PKM_CREDENTIAL_KEY=env.get("PKM_CREDENTIAL_KEY", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()),
    )
    ENV_FILE.write_text("".join(f"{key}={value}\n" for key, value in env.items()))
    ENV_FILE.chmod(0o600)
    current = existing_web_port()
    if current is not None:
        port = current
    else:
        port = next((candidate for candidate in PORTS if free(candidate)), None)
        if port is None:
            print("15173–15273 端口均被占用，无法启动 Web 服务。", file=sys.stderr)
            return 1

    current_storage = existing_service_port("minio", 9000)
    if current_storage is not None:
        storage_port = current_storage
    else:
        storage_port = next((candidate for candidate in OBJECT_STORAGE_PORTS if free(candidate)), None)
        if storage_port is None:
            print("19000–19099 端口均被占用，无法启动对象存储服务。", file=sys.stderr)
            return 1

    env.update(WEB_HOST_PORT=str(port), OBJECT_STORAGE_HOST_PORT=str(storage_port))
    ENV_FILE.write_text("".join(f"{key}={value}\n" for key, value in env.items()))
    ENV_FILE.chmod(0o600)

    result = subprocess.run(
        ["docker", "compose", "--env-file", str(ENV_FILE), "--profile", "office", "up", "-d", "--build", "--wait"],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        print("Compose 启动失败；请检查 docker compose ps 和服务日志。", file=sys.stderr)
        return result.returncode
    print(f"本地入口：http://127.0.0.1:{port}")
    print(f"本地对象存储 S3 API：http://127.0.0.1:{storage_port}")
    print(f"API 文档：http://127.0.0.1:{port}/docs")
    print("模型下载：docker compose --env-file .env.local --profile model-setup run --rm model-init")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
