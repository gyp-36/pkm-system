"""Persistent retrieval conversation API verification with disposable accounts."""

import uuid

from fastapi.testclient import TestClient

from app import conversations as conversations_module
from app.main import app
from app.maintenance import purge_accounts
from app.db import SessionLocal


def checked(client: TestClient, method: str, path: str, expected: int, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code == expected, (method, path, response.status_code, response.text[:700])
    return response.json() if response.content else None


def main() -> None:
    account_ids: list[uuid.UUID] = []
    original_search = conversations_module.search_notes
    calls = []

    def fake_search(_db, user_id, question, *, mode, limit):
        calls.append((user_id, question, mode, limit))
        return {
            "items": [{
                "note_id": "7d2e5ec1-cbe3-43bc-b38a-33825a1b39de",
                "title": "检索验收笔记",
                "notebook_id": None,
                "version": 3,
                "source_field": "body",
                "start_offset": 4,
                "end_offset": 12,
                "snippet": "快照原文片段",
                "updated_at": "2026-10-03T00:00:00+00:00",
                "score": 0.02,
                "match_source": "semantic",
            }],
            "semantic_status": "unavailable" if question == "降级验证" else "ready",
        }

    conversations_module.search_notes = fake_search
    try:
        with TestClient(app) as alice, TestClient(app) as bob:
            suffix = uuid.uuid4().hex[:10]
            alice_email = f"conv-a-{suffix}@example.com"
            password = "TestPassword123!"
            first = checked(alice, "POST", "/v1/auth/register", 201, json={"email": alice_email, "password": password})
            second = checked(bob, "POST", "/v1/auth/register", 201, json={"email": f"conv-b-{suffix}@example.com", "password": "TestPassword123!"})
            account_ids = [uuid.UUID(first["id"]), uuid.UUID(second["id"])]

            created = checked(alice, "POST", "/v1/assistant/conversations", 201)
            assert created["title"] == "新对话"
            assert checked(alice, "GET", "/v1/assistant/conversations", 200)["items"][0]["id"] == created["id"]
            sent = checked(
                alice,
                "POST",
                f"/v1/assistant/conversations/{created['id']}/messages",
                201,
                json={"question": "  第一个问题  "},
            )
            assert sent["title"] == "第一个问题"
            assert [item["role"] for item in sent["messages"]] == ["user", "assistant"]
            assert sent["messages"][0]["content"] == {"text": "第一个问题"}
            assert sent["messages"][1]["content"]["items"][0]["snippet"] == "快照原文片段"
            assert sent["messages"][1]["content"]["semantic_status"] == "ready"
            checked(
                alice,
                "POST",
                f"/v1/assistant/conversations/{created['id']}/messages",
                201,
                json={"question": "降级验证"},
            )
            assert calls == [
                (account_ids[0], "第一个问题", "hybrid", 10),
                (account_ids[0], "降级验证", "hybrid", 10),
            ]
            restored = checked(alice, "GET", f"/v1/assistant/conversations/{created['id']}", 200)
            assert len(restored["messages"]) == 4
            assert restored["messages"][0]["content"] == {"text": "第一个问题"}
            assert restored["messages"][1]["content"]["items"][0]["snippet"] == "快照原文片段"
            assert restored["messages"][3]["content"]["semantic_status"] == "unavailable"
            long_question = "无字数限制" * 40
            long_sent = checked(
                alice,
                "POST",
                f"/v1/assistant/conversations/{created['id']}/messages",
                201,
                json={"question": long_question},
            )
            assert long_sent["messages"][0]["content"]["text"] == long_question
            renamed = checked(alice, "PATCH", f"/v1/assistant/conversations/{created['id']}", 200, json={"title": "  自定义标题  "})
            assert renamed["title"] == "自定义标题"
            checked(alice, "PATCH", f"/v1/assistant/conversations/{created['id']}", 422, json={"title": "   "})
            checked(alice, "POST", "/v1/auth/logout", 204)
            checked(alice, "POST", "/v1/auth/login", 200, json={"email": alice_email, "password": password})
            assert len(checked(alice, "GET", f"/v1/assistant/conversations/{created['id']}", 200)["messages"]) == 6
            checked(bob, "GET", f"/v1/assistant/conversations/{created['id']}", 404)
            checked(bob, "POST", f"/v1/assistant/conversations/{created['id']}/messages", 404, json={"question": "越权"})
            checked(bob, "PATCH", f"/v1/assistant/conversations/{created['id']}", 404, json={"title": "越权"})
            checked(bob, "DELETE", f"/v1/assistant/conversations/{created['id']}", 404)
            assert checked(bob, "GET", "/v1/assistant/conversations", 200)["items"] == []
            checked(alice, "POST", f"/v1/assistant/conversations/{created['id']}/messages", 422, json={"question": "   "})
            checked(alice, "DELETE", f"/v1/assistant/conversations/{created['id']}", 204)
            assert checked(alice, "GET", "/v1/assistant/conversations", 200)["items"] == []
            checked(alice, "GET", f"/v1/assistant/conversations/{created['id']}", 404)
            with TestClient(app) as anonymous:
                checked(anonymous, "GET", "/v1/assistant/conversations", 401)
        print("persistent conversations, snapshots, retrieval fallback, unlimited questions, rename, delete, validation, and account isolation passed")
    finally:
        conversations_module.search_notes = original_search
        if account_ids:
            with SessionLocal.begin() as db:
                purge_accounts(db, account_ids)


if __name__ == "__main__":
    main()
