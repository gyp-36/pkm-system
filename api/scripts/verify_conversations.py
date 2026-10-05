"""Persistent knowledge-grounded conversation API verification with disposable accounts."""

import uuid

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.assistant import conversations as conversations_module
from app.main import app
from app.ops.maintenance import purge_accounts
from app.core.db import SessionLocal


def checked(client: TestClient, method: str, path: str, expected: int, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code == expected, (method, path, response.status_code, response.text[:700])
    return response.json() if response.content else None


def main() -> None:
    account_ids: list[uuid.UUID] = []
    original_answer = conversations_module.answer_question
    calls = []
    fail_next = False

    def fake_answer(question, _db, user_id, history=None, *, limit_checked=False, trace=None):
        nonlocal fail_next
        if fail_next:
            fail_next = False
            raise HTTPException(status_code=409, detail="请先配置聊天模型连接")
        calls.append((user_id, question, history or []))
        return {
            "answer": f"根据笔记，答案是快照原文片段。[S1]（问题：{question[:24]}）",
            "citations": [{
                "citation_id": "S1",
                "note_id": "7d2e5ec1-cbe3-43bc-b38a-33825a1b39de",
                "note_version": 3,
                "title": "检索验收笔记",
                "source_field": "body",
                "start_offset": 4,
                "end_offset": 12,
                "quote": "快照原文片段",
            }],
            "semantic_status": "unavailable" if question == "降级验证" else "ready",
        }

    conversations_module.answer_question = fake_answer
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
            assert sent["messages"][1]["content"]["answer"].startswith("根据笔记")
            assert sent["messages"][1]["content"]["citations"][0]["quote"] == "快照原文片段"
            assert sent["messages"][1]["content"]["semantic_status"] == "ready"
            checked(
                alice,
                "POST",
                f"/v1/assistant/conversations/{created['id']}/messages",
                201,
                json={"question": "降级验证"},
            )
            assert [call[:2] for call in calls] == [
                (account_ids[0], "第一个问题"),
                (account_ids[0], "降级验证"),
            ]
            assert len(calls[0][2]) == 0
            assert len(calls[1][2]) == 2
            assert "[S1]" not in calls[1][2][1]["content"]
            restored = checked(alice, "GET", f"/v1/assistant/conversations/{created['id']}", 200)
            assert len(restored["messages"]) == 4
            assert restored["messages"][0]["content"] == {"text": "第一个问题"}
            assert restored["messages"][1]["content"]["citations"][0]["quote"] == "快照原文片段"
            assert restored["messages"][3]["content"]["semantic_status"] == "unavailable"
            long_question = "无字数限制" * 500
            long_sent = checked(
                alice,
                "POST",
                f"/v1/assistant/conversations/{created['id']}/messages",
                201,
                json={"question": long_question},
            )
            assert long_sent["messages"][0]["content"]["text"] == long_question
            assert len(calls[-1][2]) == 4
            for index in range(3):
                checked(
                    alice,
                    "POST",
                    f"/v1/assistant/conversations/{created['id']}/messages",
                    201,
                    json={"question": f"上下文上限验证 {index + 1}"},
                )
            assert [len(call[2]) for call in calls[-3:]] == [6, 8, 8]
            assert len(calls[-3][2][4]["content"]) == conversations_module.MAX_HISTORY_MESSAGE_CHARS

            before_failed_turn = len(checked(alice, "GET", f"/v1/assistant/conversations/{created['id']}", 200)["messages"])
            fail_next = True
            checked(
                alice,
                "POST",
                f"/v1/assistant/conversations/{created['id']}/messages",
                409,
                json={"question": "模型未配置"},
            )
            after_failed_turn = len(checked(alice, "GET", f"/v1/assistant/conversations/{created['id']}", 200)["messages"])
            assert after_failed_turn == before_failed_turn
            renamed = checked(alice, "PATCH", f"/v1/assistant/conversations/{created['id']}", 200, json={"title": "  自定义标题  "})
            assert renamed["title"] == "自定义标题"
            checked(alice, "PATCH", f"/v1/assistant/conversations/{created['id']}", 422, json={"title": "   "})
            checked(alice, "POST", "/v1/auth/logout", 204)
            checked(alice, "POST", "/v1/auth/login", 200, json={"email": alice_email, "password": password})
            assert len(checked(alice, "GET", f"/v1/assistant/conversations/{created['id']}", 200)["messages"]) == 12
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
        print("知识库持久化对话、引用、历史记录限制、失败轮次回滚、重命名、删除、校验和账户隔离检查均已通过")
    finally:
        conversations_module.answer_question = original_answer
        if account_ids:
            with SessionLocal.begin() as db:
                purge_accounts(db, account_ids)


if __name__ == "__main__":
    main()
