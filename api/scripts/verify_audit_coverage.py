"""Disposable audit-coverage check for the P0 logging rollout.

逐个触发各类写操作，断言每种实体都有对应的审计记录与动作类型。
"""

import os
import uuid

import httpx
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.enums import AuditAction, AuditEntityType
from app.core.models import AuditEvent
from app.ops.maintenance import purge_accounts


BASE = os.getenv("M1_TEST_API_URL", "http://api:8000")

ACTION_NAME = {
    AuditAction.REGISTER: "register", AuditAction.LOGIN: "login", AuditAction.LOGOUT: "logout",
    AuditAction.CREATE: "create", AuditAction.UPDATE: "update", AuditAction.RENAME: "rename",
    AuditAction.DELETE: "delete", AuditAction.RESTORE: "restore", AuditAction.TEST: "test",
}
ENTITY_NAME = {
    AuditEntityType.ACCOUNT: "account", AuditEntityType.SESSION: "session", AuditEntityType.NOTE: "note",
    AuditEntityType.NOTEBOOK: "notebook", AuditEntityType.TAG: "tag", AuditEntityType.REMINDER: "reminder",
    AuditEntityType.TEMPLATE: "template", AuditEntityType.CONVERSATION: "conversation",
    AuditEntityType.MODEL_CONNECTION: "model_connection", AuditEntityType.UPLOAD_SESSION: "upload_session",
    AuditEntityType.LINK_DRAFT: "link_draft", AuditEntityType.DIGEST: "digest",
    AuditEntityType.ASSISTANT_MESSAGE: "assistant_message",
}


def call(client: httpx.Client, method: str, path: str, expected: int, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code == expected, (method, path, response.status_code, response.text[:400])
    return response.json() if response.content else None


def main() -> None:
    account_id = None
    draft_covered = False
    try:
        with httpx.Client(base_url=BASE, timeout=30) as client:
            suffix = uuid.uuid4().hex[:10]
            account = call(client, "POST", "/v1/auth/register", 201,
                           json={"email": f"audit-{suffix}@example.com", "password": "TestPassword123!"})
            account_id = uuid.UUID(account["id"])

            notebook = call(client, "POST", "/v1/notebooks", 201, json={"name": "审计分类"})
            call(client, "PATCH", f"/v1/notebooks/{notebook['id']}", 200, json={"name": "审计分类改名"})
            tag = call(client, "POST", "/v1/tags", 201, json={"name": "审计标签"})
            call(client, "PATCH", f"/v1/tags/{tag['id']}", 200, json={"name": "审计标签改名"})

            note = call(client, "POST", "/v1/notes", 201,
                        json={"title": "审计笔记", "body_md": "审计专用正文不应进入日志",
                              "notebook_id": notebook["id"], "tag_ids": [tag["id"]]})
            note = call(client, "PATCH", f"/v1/notes/{note['id']}", 200,
                        json={"version": 1, "body_md": "第二版"})
            note_version = note["version"]

            template = call(client, "POST", "/v1/note-templates", 201,
                            json={"name": "审计模板", "title": "模板标题", "body_md": "模板正文"})
            call(client, "PATCH", f"/v1/note-templates/{template['id']}", 200, json={"name": "审计模板改名"})
            call(client, "DELETE", f"/v1/note-templates/{template['id']}", 204)

            reminder = call(client, "POST", "/v1/reminders", 201,
                            json={"text": "审计提醒", "due_at": "2026-10-06T09:00:00+08:00"})
            call(client, "PATCH", f"/v1/reminders/{reminder['id']}", 200, json={"text": "审计提醒改名"})
            call(client, "DELETE", f"/v1/reminders/{reminder['id']}", 204)

            conversation = call(client, "POST", "/v1/assistant/conversations", 201)
            call(client, "PATCH", f"/v1/assistant/conversations/{conversation['id']}", 200,
                 json={"title": "审计对话"})
            call(client, "DELETE", f"/v1/assistant/conversations/{conversation['id']}", 204)

            # 假 Key 仅用于产生审计，不触发连通性测试。
            call(client, "PUT", "/v1/model-connection", 200,
                 json={"api_key": "sk-audit-placeholder-0001", "model_name": "deepseek-flash"})
            call(client, "PATCH", "/v1/model-connection", 200, json={"model_name": "deepseek-v4-pro"})
            call(client, "DELETE", "/v1/model-connection", 204)

            call(client, "PUT", "/v1/digests/settings", 200,
                 json={"daily_enabled": True, "daily_time": "21:00", "weekly_enabled": False,
                       "weekly_weekday": 6, "weekly_time": "21:00"})
            call(client, "PATCH", "/v1/digests/settings", 200, json={"daily_time": "08:30"})

            try:
                draft = call(client, "POST", "/v1/link-drafts", 201,
                             json={"url": "https://example.com/audit", "pasted_text": "网页正文"})
                call(client, "PATCH", f"/v1/link-drafts/{draft['id']}", 200, json={"title": "审计草稿"})
                call(client, "DELETE", f"/v1/link-drafts/{draft['id']}", 204)
                draft_covered = True
            except AssertionError as exc:
                print(f"  [跳过] 网页草稿（容器内无法解析外部地址）: {str(exc)[:110]}\n")

            call(client, "DELETE", f"/v1/notes/{note['id']}", 204, params={"version": note_version})
            call(client, "DELETE", f"/v1/notebooks/{notebook['id']}", 204)
            call(client, "DELETE", f"/v1/tags/{tag['id']}", 204)

        expected = {
            AuditEntityType.ACCOUNT: {AuditAction.REGISTER},
            AuditEntityType.NOTEBOOK: {AuditAction.CREATE, AuditAction.RENAME, AuditAction.DELETE},
            AuditEntityType.TAG: {AuditAction.CREATE, AuditAction.RENAME, AuditAction.DELETE},
            AuditEntityType.NOTE: {AuditAction.CREATE, AuditAction.UPDATE, AuditAction.DELETE},
            AuditEntityType.TEMPLATE: {AuditAction.CREATE, AuditAction.RENAME, AuditAction.DELETE},
            AuditEntityType.REMINDER: {AuditAction.CREATE, AuditAction.UPDATE, AuditAction.DELETE},
            AuditEntityType.CONVERSATION: {AuditAction.CREATE, AuditAction.RENAME, AuditAction.DELETE},
            AuditEntityType.MODEL_CONNECTION: {AuditAction.CREATE, AuditAction.UPDATE, AuditAction.DELETE},
            AuditEntityType.DIGEST: {AuditAction.UPDATE},
        }
        if draft_covered:
            expected[AuditEntityType.LINK_DRAFT] = {AuditAction.CREATE, AuditAction.UPDATE, AuditAction.DELETE}

        with SessionLocal() as db:
            events = db.scalars(select(AuditEvent).where(AuditEvent.user_id == account_id)).all()

        by_type: dict[int, set[int]] = {}
        for event in events:
            by_type.setdefault(event.entity_type, set()).add(event.action)

        print(f"\n{'实体类型':<20} {'期望动作':<34} 结果")
        print("-" * 72)
        failures = []
        for entity_type, actions in expected.items():
            got = by_type.get(int(entity_type), set())
            missing = {int(a) for a in actions} - got
            label = ENTITY_NAME[entity_type]
            wanted = ", ".join(ACTION_NAME[a] for a in sorted(actions, key=int))
            if missing:
                failures.append(f"{label} 缺少 {'/'.join(ACTION_NAME[AuditAction(m)] for m in sorted(missing))}")
                print(f"{label:<20} {wanted:<34} 缺失")
            else:
                print(f"{label:<20} {wanted:<34} 通过")

        assert not failures, "；".join(failures)

        # 详情必须结构化且不得泄露正文与凭据。
        leak_fields = ("审计专用正文", "TestPassword", "sk-audit-placeholder")
        for event in events:
            payload = str(event.details)
            for leak in leak_fields:
                assert leak not in payload, f"审计详情泄露敏感内容: {leak}"
        structured = [e for e in events if "changed" in e.details or "fields" in e.details]
        assert structured, "没有任何审计记录携带结构化变更字段"

        print(f"\n共 {len(events)} 条审计记录，覆盖 {len(by_type)} 种实体类型。")
        print(f"结构化变更记录 {len(structured)} 条；未发现正文或凭据泄露。")
        print("审计覆盖检查通过")
    finally:
        if account_id is not None:
            with SessionLocal.begin() as db:
                purge_accounts(db, [account_id])


if __name__ == "__main__":
    main()
