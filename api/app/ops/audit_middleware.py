"""Request-level access logging written through an isolated session.

业务审计由 `record_event` 加入调用方事务，一旦业务回滚就一并消失——
「越权 404」「版本冲突 409」「参数校验 422」这些最该留痕的动作反而没有痕迹。

本中间件改用**独立的数据库会话**落库，与业务事务完全解耦，因此无论请求成功与否都能记录。

两个实现要点：

1. 采用纯 ASGI 中间件而非 `BaseHTTPMiddleware`。后者会介入响应体流转，
   对项目中的 SSE 流式接口（`/v1/conversations/{id}/messages/stream`）不友好；
   纯 ASGI 版本只旁听 `send` 消息，零缓冲。
2. 与业务共用同一个 `contextvars` 上下文（同一调用链、同一 task），
   因此业务侧 `record_event` 能自动拿到本次请求的 `request_id`，无需透传参数。
"""

from __future__ import annotations

import logging
import time
import uuid

from datetime import datetime, timezone

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from app.auth.auth import COOKIE_NAME, token_digest
from app.core.db import SessionLocal
from app.core.enums import AuditAction, AuditActor, AuditEntityType, AuditOutcome
from app.core.models import AccessLog, AuditEvent, UserSession
from app.core.request_context import request_id_var


log = logging.getLogger(__name__)

# 心跳、文档与静态资源会淹没日志表，直接跳过。
SKIP_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico")

# 写方法到审计动作的映射，用于为被拒请求补记一条失败事件。
WRITE_METHODS = {
    "POST": AuditAction.CREATE,
    "PUT": AuditAction.UPDATE,
    "PATCH": AuditAction.UPDATE,
    "DELETE": AuditAction.DELETE,
}

MAX_PATH = 255
MAX_UA = 512


def _header(scope: dict, name: bytes) -> str | None:
    for key, value in scope.get("headers") or ():
        if key == name:
            return value.decode("latin-1", "replace")
    return None


def _resolve_user_id(db, request: Request) -> uuid.UUID | None:
    """从会话 Cookie 反查用户。

    查询失败（未登录、Cookie 失效、账号停用）一律返回 None，不影响请求本身。
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        return db.scalar(
            select(UserSession.user_id).where(
                UserSession.token_hash == token_digest(token),
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > datetime.now(timezone.utc),
            )
        )
    except Exception:  # noqa: BLE001 - 审计查询失败不得影响请求
        return None


class AuditAccessMiddleware:
    """记录全量 HTTP 访问，并为失败的写请求补记一条失败审计。"""

    def __init__(self, app) -> None:
        self.app = app

    @staticmethod
    def _skip(path: str) -> bool:
        return path.startswith(SKIP_PREFIXES)

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if self._skip(path):
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4()
        token = request_id_var.set(request_id)
        started_at = time.perf_counter()
        # 进程内可变容器，供 send 包装器回写真实状态码。
        state = {"status": 500}

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                message.setdefault("headers", []).append(
                    (b"x-request-id", str(request_id).encode())
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            try:
                await run_in_threadpool(
                    self._persist, scope, request_id, state["status"], duration_ms
                )
            except Exception:  # noqa: BLE001 - 日志写入失败绝不能影响主流程
                log.warning("access log write failed", exc_info=True)

    @staticmethod
    def _persist(scope: dict, request_id: uuid.UUID, status_code: int, duration_ms: int) -> None:
        request = Request(scope)
        with SessionLocal() as db:                       # 独立会话、独立事务
            user_id = _resolve_user_id(db, request)
            db.add(AccessLog(
                request_id=request_id,
                user_id=user_id,
                method=scope.get("method", "")[:8],
                path=scope.get("path", "")[:MAX_PATH],
                status_code=status_code,
                duration_ms=duration_ms,
                ip=(scope.get("client") or (None, None))[0],
                user_agent=(_header(scope, b"user-agent") or "")[:MAX_UA] or None,
            ))
            # 被拒的写请求额外补一条失败审计，使「尝试删除但被拒」可追溯。
            # 未登录请求无法归属用户（user_id 非空约束），只在访问日志中留痕。
            action = WRITE_METHODS.get(scope.get("method", ""))
            if action is not None and status_code >= 400 and user_id is not None:
                db.add(AuditEvent(
                    user_id=user_id,
                    actor_type=int(AuditActor.USER),
                    action=int(action),
                    entity_type=int(AuditEntityType.REQUEST),
                    entity_id=request_id,
                    details={"status_code": status_code},
                    request_id=request_id,
                    actor_id=user_id,
                    outcome=int(AuditOutcome.FAILED),
                ))
            db.commit()
