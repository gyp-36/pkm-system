"""P2 audit governance check: retention, query exit, worker correlation.

验证四件事：

1. **永久删除不销毁审计**：笔记从回收站物理清除后，它的历史审计行必须全部留存，
   并新增一条 `purged=True` 的删除事件——审计行要活得比笔记久；
2. **排障查询出口可用**：`scripts.query_audit` 能把 smallint 枚举还原成语义字符串，
   且对含 `key`/`token`/`password` 的键值脱敏；
3. **访问日志有保留期**：过期行被清理、未过期行保留，且**业务审计一行不动**；
4. **worker 关联 ID**：后台任务用被处理单元 ID 绑定上下文后，
   它产生的审计行也带上 `request_id`。
"""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, func, select

from app.core.db import SessionLocal
from app.core.enums import AuditAction, AuditEntityType
from app.core.lifecycle import record_event
from app.core.models import AccessLog, AuditEvent
from app.core.request_context import correlation
from app.ops.maintenance import purge_access_logs, purge_accounts


BASE = os.getenv("M1_TEST_API_URL", "http://api:8000")
PASSWORD = "TestPassword123!"
PURGE_RETENTION_DAYS = 90


def call(client: httpx.Client, method: str, path: str, expected: int, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code == expected, (method, path, response.status_code, response.text[:400])
    return response.json() if response.content else None


def run_query(*args: str) -> str:
    """以子进程方式调用运维脚本，验证真实的 CLI 行为而非内部函数。"""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.query_audit", *args],
        capture_output=True, text=True, cwd="/app", timeout=120,
    )
    assert result.returncode == 0, f"query_audit 退出码 {result.returncode}\n{result.stderr[:500]}"
    return result.stdout


def main() -> None:
    account_id: uuid.UUID | None = None
    probe_request_id = uuid.uuid4()
    try:
        suffix = uuid.uuid4().hex[:10]
        with httpx.Client(base_url=BASE, timeout=30) as client:
            account = call(client, "POST", "/v1/auth/register", 201,
                           json={"email": f"gov-{suffix}@example.com", "password": PASSWORD})
            account_id = uuid.UUID(account["id"])

            note = call(client, "POST", "/v1/notes", 201,
                        json={"title": "治理笔记", "body_md": "治理专用正文不应进入日志"})
            note = call(client, "PATCH", f"/v1/notes/{note['id']}", 200,
                        json={"version": note["version"], "body_md": "第二版正文"})
            note_id = uuid.UUID(note["id"])

            call(client, "DELETE", f"/v1/notes/{note_id}", 204, params={"version": note["version"]})

            # --- 场景 1：永久删除后审计必须完整留存 ---
            with SessionLocal() as db:
                before_purge = db.scalars(select(AuditEvent).where(
                    AuditEvent.user_id == account_id,
                    AuditEvent.entity_type == int(AuditEntityType.NOTE),
                    AuditEvent.entity_id == note_id,
                )).all()
            assert before_purge, "归档前就不存在审计行，前置条件不成立"

            # 回收站物理清除：归档接口不需要 version 参数
            call(client, "DELETE", f"/v1/notes/archive/{note_id}", 204)

        with SessionLocal() as db:
            after_purge = db.scalars(select(AuditEvent).where(
                AuditEvent.user_id == account_id,
                AuditEvent.entity_type == int(AuditEntityType.NOTE),
                AuditEvent.entity_id == note_id,
            )).all()
            note_exists = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == note_id))

        actions = sorted({e.action for e in after_purge})
        purged = [e for e in after_purge if (e.details or {}).get("purged")]
        print("\n场景 1 · 永久删除后的审计留存")
        print(f"  归档前审计 {len(before_purge)} 条 → 物理清除后 {len(after_purge)} 条")
        print(f"  动作集合 {[AuditAction(a).name for a in actions]}")
        assert len(after_purge) > len(before_purge), "物理清除销毁了历史审计行"
        assert any(a == int(AuditAction.CREATE) for a in actions), "CREATE 历史审计未留存"
        assert purged, "缺少 purged=True 的删除事件"
        assert note_exists == len(after_purge)
        print("  ✅ 历史审计全部留存，并新增 purged 删除事件")

        # --- 场景 2：排障查询出口 ---
        raw = run_query("--entity-id", str(note_id))
        assert "DELETE" in raw and "CREATE" in raw, "查询输出未还原语义枚举"
        assert "治理专用正文" not in raw, "查询输出泄露正文"

        # 注入一条含敏感键的审计，验证脱敏（键名判断，不看值）
        with SessionLocal.begin() as db:
            db.add(AuditEvent(
                user_id=account_id,
                actor_type=1, action=int(AuditAction.UPDATE),
                entity_type=int(AuditEntityType.NOTE), entity_id=note_id,
                details={"token": "SHOULD-NOT-APPEAR", "api_key": "SHOULD-NOT-APPEAR", "changed": ["title"]},
                request_id=probe_request_id, actor_id=account_id, outcome=1,
            ))
        redacted = run_query("--entity-id", str(note_id), "--json")
        assert "SHOULD-NOT-APPEAR" not in redacted, "脱敏失效：敏感键值被打印"
        payload = json.loads(redacted)
        assert "***" in redacted, "未看到脱敏占位符"
        assert any(ev["request_id"] == str(probe_request_id) for ev in payload["audit_events"]), \
            "按 entity_id 未取到新注入的审计"
        print("\n场景 2 · 排障查询出口")
        print("  语义枚举还原正常；含 token / api_key 的键值已脱敏为 ***")

        # --- 场景 3：访问日志保留期 ---
        stale_at = datetime.now(timezone.utc) - timedelta(days=PURGE_RETENTION_DAYS + 10)
        stale_rid, fresh_rid = uuid.uuid4(), uuid.uuid4()
        with SessionLocal.begin() as db:
            db.add_all([
                AccessLog(request_id=stale_rid, user_id=account_id, method="GET", path="/v1/governance/stale",
                          status_code=200, duration_ms=1, created_at=stale_at),
                AccessLog(request_id=fresh_rid, user_id=account_id, method="GET", path="/v1/governance/fresh",
                          status_code=200, duration_ms=1, created_at=datetime.now(timezone.utc)),
            ])

        with SessionLocal() as db:
            audit_before = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.user_id == account_id))

        planned = purge_access_logs(days=PURGE_RETENTION_DAYS, dry_run=True)
        assert planned >= 1, "dry-run 未统计出过期访问日志"
        removed = purge_access_logs(days=PURGE_RETENTION_DAYS)

        with SessionLocal() as db:
            stale_left = db.scalar(select(func.count()).select_from(AccessLog).where(AccessLog.request_id == stale_rid))
            fresh_left = db.scalar(select(func.count()).select_from(AccessLog).where(AccessLog.request_id == fresh_rid))
            audit_after = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.user_id == account_id))

        print("\n场景 3 · 访问日志保留期（%d 天）" % PURGE_RETENTION_DAYS)
        print(f"  dry-run 预估 {planned} 条 → 实际删除 {removed} 条")
        print(f"  过期行剩余 {stale_left}，未过期行剩余 {fresh_left}")
        assert stale_left == 0, "过期访问日志未被清理"
        assert fresh_left == 1, "未过期的访问日志被误删"
        assert removed == planned, f"实际删除 {removed} 条与预估 {planned} 条不一致"
        assert audit_after == audit_before, "清理访问日志时误伤了业务审计"
        print("  ✅ 只清理过期访问日志，业务审计一行未动")

        # --- 场景 4：worker 关联 ID 落到审计行 ---
        worker_unit_id = uuid.uuid4()
        with SessionLocal.begin() as db:
            with correlation(worker_unit_id):
                record_event(db, account_id, AuditAction.UPDATE, AuditEntityType.NOTE, note_id,
                             details={"source": "worker"})
        with SessionLocal() as db:
            worker_event = db.scalar(select(AuditEvent).where(
                AuditEvent.request_id == worker_unit_id,
                AuditEvent.entity_type == int(AuditEntityType.NOTE),
            ))
        assert worker_event is not None, "worker 关联 ID 未落到审计行"
        assert worker_event.details.get("source") == "worker"
        print("\n场景 4 · 后台任务关联 ID")
        print(f"  关联 ID {str(worker_unit_id)[:8]}… 已写入审计行 request_id")
        print("  ✅ 后台任务产生的审计同样可按 request_id 检索")

        print("\n审计治理检查通过")
    finally:
        if account_id is not None:
            with SessionLocal.begin() as db:
                db.execute(delete(AccessLog).where(AccessLog.user_id == account_id))
                purge_accounts(db, [account_id])


if __name__ == "__main__":
    main()
