"""P1 audit observability check: request tracing and failure persistence.

验证三件事：

1. 正常业务审计带 `request_id` / `actor_id`，并能与访问日志按 `request_id` 关联；
2. 失败请求（越权 404、版本冲突 409、重复注册 409）在 `pkm_access_logs` 中留痕；
3. 被拒的写请求额外产生 `outcome=FAILED` 的业务审计，密码错误单独留痕。

这正是 P0 遗留的核心缺陷：业务审计写在调用方事务里，业务一回滚就消失。
"""

import os
import time
import uuid

import httpx
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.core.enums import AuditAction, AuditEntityType, AuditOutcome
from app.core.models import AccessLog, AuditEvent
from app.ops.maintenance import purge_accounts


BASE = os.getenv("M1_TEST_API_URL", "http://api:8000")
PASSWORD = "TestPassword123!"


def request(client: httpx.Client, method: str, path: str, expected: int, **kwargs) -> httpx.Response:
    response = client.request(method, path, **kwargs)
    assert response.status_code == expected, (method, path, response.status_code, response.text[:300])
    assert response.headers.get("x-request-id"), f"{method} {path} 缺少 X-Request-Id 响应头"
    return response


def load_access(rids: list[uuid.UUID], timeout: float = 5.0) -> dict[uuid.UUID, AccessLog]:
    """轮询等待访问日志落库。

    中间件在响应发送完毕后才写日志（与业务事务解耦的代价），
    因此客户端收到响应时日志可能尚未提交，必须等待而非立即断言。
    """
    deadline = time.monotonic() + timeout
    rows: dict[uuid.UUID, AccessLog] = {}
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            rows = {row.request_id: row for row in db.scalars(
                select(AccessLog).where(AccessLog.request_id.in_(rids))).all()
            }
        if len(rows) >= len(rids):
            return rows
        time.sleep(0.1)
    return rows


def main() -> None:
    account_ids: list[uuid.UUID] = []
    seen: dict[str, str] = {}
    try:
        suffix = uuid.uuid4().hex[:10]
        email_owner = f"obs-owner-{suffix}@example.com"
        email_other = f"obs-other-{suffix}@example.com"

        with httpx.Client(base_url=BASE, timeout=30) as owner, httpx.Client(base_url=BASE, timeout=30) as other:
            registered = request(owner, "POST", "/v1/auth/register", 201,
                                 json={"email": email_owner, "password": PASSWORD})
            account_ids.append(uuid.UUID(registered.json()["id"]))

            # --- 正常链路：成功审计必须能关联到访问日志 ---
            note = request(owner, "POST", "/v1/notes", 201,
                           json={"title": "可观测性笔记", "body_md": "正文不应进入日志"}).json()
            updated = request(owner, "PATCH", f"/v1/notes/{note['id']}", 200,
                              json={"version": note["version"], "title": "改名后的标题"})
            seen["正常更新"] = updated.headers["x-request-id"]
            note_version = updated.json()["version"]

            other_registered = request(other, "POST", "/v1/auth/register", 201,
                                       json={"email": email_other, "password": PASSWORD})
            other_id = uuid.UUID(other_registered.json()["id"])
            account_ids.append(other_id)

            # --- 越权：他人笔记不可见，返回 404 ---
            denied = request(other, "DELETE", f"/v1/notes/{note['id']}", 404,
                             params={"version": note_version})
            seen["越权删除"] = denied.headers["x-request-id"]

            # --- 版本冲突：携带过期版本号 ---
            conflict = request(owner, "PATCH", f"/v1/notes/{note['id']}", 409,
                               json={"version": 99999, "title": "冲突写入"})
            seen["版本冲突"] = conflict.headers["x-request-id"]

            # --- 重复注册：业务 flush 后失败，审计随事务回滚消失 ---
            dup = request(owner, "POST", "/v1/auth/register", 409,
                          json={"email": email_owner, "password": PASSWORD})
            seen["重复注册"] = dup.headers["x-request-id"]

            # --- 密码错误：请求无有效凭据可归属，须由业务侧独立补记 ---
            bad_login = owner.post("/v1/auth/login", json={"email": email_owner, "password": "WrongPassword123!"})
            assert bad_login.status_code == 401, bad_login.text[:200]
            seen["密码错误"] = bad_login.headers["x-request-id"]

            # --- 健康检查必须被跳过，否则日志表会被心跳淹没 ---
            owner.get("/health/live")

        rids = {label: uuid.UUID(value) for label, value in seen.items()}
        access = load_access(list(rids.values()))

        with SessionLocal() as db:
            events = db.scalars(select(AuditEvent).where(AuditEvent.user_id.in_(account_ids))).all()
            health_rows = db.scalar(select(AccessLog).where(AccessLog.path.like("/health%")))

        print(f"\n{'场景':<10}{'状态码':<8}{'访问日志':<10}结果")
        print("-" * 56)
        failures: list[str] = []
        for label, rid in rids.items():
            row = access.get(rid)
            if row is None:
                failures.append(f"{label} 未产生访问日志")
                print(f"{label:<10}{'-':<8}{'缺失':<10}失败")
            else:
                print(f"{label:<10}{row.status_code:<8}{row.method:<10}通过")

        assert not failures, "；".join(failures)
        assert access[rids["正常更新"]].status_code == 200
        assert access[rids["越权删除"]].status_code == 404
        assert access[rids["越权删除"]].user_id == other_id, "越权尝试未归属到发起账号"
        assert access[rids["版本冲突"]].status_code == 409
        assert access[rids["重复注册"]].status_code == 409
        assert access[rids["密码错误"]].status_code == 401

        assert health_rows is None, "健康检查不应进入访问日志"

        # --- 业务审计必须都能关联到请求 ---
        orphan = [e for e in events if e.request_id is None]
        assert not orphan, f"{len(orphan)} 条业务审计缺少 request_id"
        assert all(e.actor_id is not None for e in events), "存在缺少 actor_id 的业务审计"
        assert all(e.outcome is not None for e in events), "存在缺少 outcome 的业务审计"

        success_note = [e for e in events
                        if e.request_id == rids["正常更新"] and e.entity_type == int(AuditEntityType.NOTE)]
        assert success_note, "正常更新未生成关联业务审计"
        assert success_note[0].outcome == int(AuditOutcome.SUCCESS)

        # --- 失败留痕：被拒的写请求必须补记 outcome=FAILED ---
        rejected = {e.request_id: e for e in events
                    if e.outcome == int(AuditOutcome.FAILED)
                    and e.entity_type == int(AuditEntityType.REQUEST)}
        for label in ("越权删除", "版本冲突"):
            event = rejected.get(rids[label])
            assert event is not None, f"{label} 未补记失败审计"
            assert event.details.get("status_code") == access[rids[label]].status_code, \
                f"{label} 失败审计状态码不一致"

        # --- 密码错误走独立会话，不依赖业务事务 ---
        bad_creds = [e for e in events
                     if e.action == int(AuditAction.LOGIN) and e.outcome == int(AuditOutcome.FAILED)]
        assert bad_creds, "密码错误未留痕"
        assert bad_creds[0].details.get("reason") == "bad_credentials"

        print("\n业务审计：%d 条，全部携带 request_id / actor_id / outcome" % len(events))
        print("失败留痕：越权 404、版本冲突 409 均补记 outcome=FAILED")
        print("独立补记：密码错误已写入业务审计（不依赖业务事务）")
        print("健康检查：未进入访问日志")
        print("\n审计可观测性检查通过")
    finally:
        rids = [uuid.UUID(value) for value in seen.values()]
        with SessionLocal.begin() as db:
            if rids:
                db.execute(delete(AccessLog).where(AccessLog.request_id.in_(rids)))
            if account_ids:
                purge_accounts(db, account_ids)


if __name__ == "__main__":
    main()
