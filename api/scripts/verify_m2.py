"""M2 acceptance with a local OpenAI-compatible fake; no external key or charge."""

import json
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.assistant import model_connection
from app.assistant.assistant import keyword_query_variants
from app.core.db import SessionLocal
from app.main import app
from app.ops.maintenance import purge_accounts
from app.core.models import ModelConnection


class FakeModelHandler(BaseHTTPRequestHandler):
    search_evidence: list[list[dict]] = []

    def log_message(self, _format: str, *_args) -> None:
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        assert payload.get("thinking") == {"type": "disabled"}
        assert 1 <= payload.get("max_tokens", 0) <= 2200
        messages = payload["messages"]
        user_content = next((m["content"] for m in messages if m["role"] == "user"), "")
        tool_messages = [m for m in messages if m["role"] == "tool"]
        if payload.get("tools") and not tool_messages:
            name = "search_personal_notes" if not (str(user_content).startswith("分析笔记") or str(user_content).startswith("{")) else "read_personal_note"
            arguments = {"question": str(user_content)} if name == "search_personal_notes" else {"note_ref": re.search(r"N\d+", str(user_content)).group(), "include_citations": True}
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}
            finish_reason = "tool_calls"
        elif tool_messages:
            try:
                evidence = json.loads(tool_messages[-1]["content"])
            except json.JSONDecodeError:
                evidence = []
            if isinstance(evidence, dict):
                evidence = evidence.get("citations", [])
            if not isinstance(evidence, list):
                evidence = []
            if evidence and "source_ref" in evidence[0]:
                FakeModelHandler.search_evidence.append(evidence)
            marker = evidence[0]["source_ref"] if evidence else "S999"
            if str(user_content).startswith("分析笔记"):
                content = json.dumps({"analysis": f"正文结构可更清晰 [{marker}]", "suggestions": [f"添加分段标题 [{marker}]"]}, ensure_ascii=False)
            elif str(user_content).startswith("{"):
                source = json.loads(user_content)
                content = json.dumps({"notebook_ref": source["notebooks"][0]["ref"] if source["notebooks"] else None, "tag_refs": [source["tags"][0]["ref"]] if source["tags"] else [], "reason": f"主题与现有分类相关 [{marker}]"}, ensure_ascii=False)
            elif "无效引用" in str(user_content):
                content = "这是无法核对的回答 [S999]"
            else:
                content = f"笔记记录了番茄钟方法 [{marker}]"
            message = {"role": "assistant", "content": content}
            finish_reason = "stop"
        elif str(user_content).startswith('{') and '"sources"' in str(user_content):
            source = json.loads(user_content)
            refs = [item['source_ref'] for item in source['sources']]
            content = json.dumps({"segments": [{"text": source['answer'] if refs else "引用无法核对，请补充资料。", "basis": "note" if refs else "uncertain", "source_refs": refs[:1], "supported": bool(refs)}]}, ensure_ascii=False)
            message = {"role": "assistant", "content": content}
            finish_reason = "stop"
        else:
            message = {"role": "assistant", "content": "连接成功"}
            finish_reason = "stop"
        response = {
            "id": "chatcmpl-local-test", "object": "chat.completion", "created": 1,
            "model": payload["model"], "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        data = json.dumps(response, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def checked(client: TestClient, method: str, path: str, expected: int, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code == expected, (method, path, response.status_code, response.text[:700])
    return response.json() if response.content else None


def main() -> None:
    variants = keyword_query_variants("不要删除 A-17 在 2026 年 10 月的记录")
    assert "A-17" in variants and "2026" in variants
    FakeModelHandler.search_evidence.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_url = model_connection.DEEPSEEK_URL
    model_connection.DEEPSEEK_URL = f"http://127.0.0.1:{server.server_port}"
    account_ids = []
    try:
        with TestClient(app) as alice, TestClient(app) as bob:
            suffix = uuid.uuid4().hex[:10]
            first = checked(alice, "POST", "/v1/auth/register", 201, json={"email": f"m2a-{suffix}@example.com", "password": "TestPassword123!"})
            second = checked(bob, "POST", "/v1/auth/register", 201, json={"email": f"m2b-{suffix}@example.com", "password": "TestPassword123!"})
            account_ids = [uuid.UUID(first["id"]), uuid.UUID(second["id"])]
            assert checked(alice, "GET", "/v1/model-connection", 200)["configured"] is False
            key = "sk-local-fake-secret"
            saved = checked(alice, "PUT", "/v1/model-connection", 200, json={"api_key": key, "model_name": "deepseek-flash"})
            assert saved["configured"] and saved["key_masked"] and key not in str(saved)
            assert checked(bob, "GET", "/v1/model-connection", 200)["configured"] is False
            with SessionLocal() as db:
                row = db.scalar(select(ModelConnection).where(ModelConnection.user_id == account_ids[0], ModelConnection.deleted_at.is_(None)))
                assert row is not None and key.encode() not in row.credential_ciphertext
            assert checked(alice, "POST", "/v1/model-connection/test", 200, json={})["ok"] is True
            notebook = checked(alice, "POST", "/v1/notebooks", 201, json={"name": "学习"})
            tag = checked(alice, "POST", "/v1/tags", 201, json={"name": "方法"})
            matching_notes = [
                checked(alice, "POST", "/v1/notes", 201, json={
                    "title": f"时间管理素材 {index}",
                    "body_md": f"番茄钟帮助我专注学习，第 {index} 条测试记录。",
                })
                for index in range(6)
            ]
            note = checked(alice, "POST", "/v1/notes", 201, json={"title": "时间管理", "body_md": "番茄钟帮助我专注学习。"})
            answer = checked(alice, "POST", "/v1/assistant/ask", 200, json={"question": "我记录了什么时间管理方法？"})
            assert answer["citations"] and answer["citations"][0]["title"] in {"时间管理", *(f"时间管理素材 {index}" for index in range(6))}
            assert answer["citations"][0]["note_id"] in {note["id"], *(item["id"] for item in matching_notes)}
            assert "时间管理" in keyword_query_variants("我记录了什么时间管理方法？")
            assert FakeModelHandler.search_evidence[0] and len(FakeModelHandler.search_evidence[0]) == 5
            rejected = checked(alice, "POST", "/v1/assistant/ask", 200, json={"question": "请根据我的笔记给出一个无效引用"})
            assert rejected["citations"] == [] and "核对" in rejected["answer"]
            analysis = checked(alice, "POST", "/v1/assistant/analyze", 200, json={"note_id": note["id"]})
            assert analysis["suggestions"] and analysis["citations"]
            suggestion = checked(alice, "POST", "/v1/assistant/classify", 200, json={"note_id": note["id"]})
            assert suggestion["notebook_id"] == notebook["id"] and suggestion["tag_ids"] == [tag["id"]]
            assert checked(alice, "GET", f"/v1/notes/{note['id']}", 200)["notebook_id"] is None  # 拒绝请求时不会写入数据。
            updated = checked(alice, "PATCH", f"/v1/notes/{note['id']}", 200, json={"version": suggestion["note_version"], "notebook_id": suggestion["notebook_id"], "tag_ids": suggestion["tag_ids"]})
            assert updated["notebook_id"] == notebook["id"] and updated["tag_ids"] == [tag["id"]]
            checked(bob, "PUT", "/v1/model-connection", 200, json={"api_key": "sk-another-fake-secret", "model_name": "deepseek-flash"})
            checked(bob, "POST", "/v1/assistant/analyze", 404, json={"note_id": note["id"]})
            checked(alice, "DELETE", "/v1/model-connection", 204)
            assert checked(alice, "GET", "/v1/model-connection", 200)["configured"] is False
            with SessionLocal() as db:
                row = db.scalar(select(ModelConnection).where(ModelConnection.user_id == account_ids[0]))
                assert row.credential_ciphertext == b"" and row.deleted_at is not None
            checked(alice, "POST", "/v1/assistant/ask", 409, json={"question": "还能提问吗？"})
        print("M2 本地关键词扩展、前 5 条证据、模型回答引用、分析、分类复核和账户隔离检查均已通过")
    finally:
        model_connection.DEEPSEEK_URL = original_url
        server.shutdown()
        server.server_close()
        if account_ids:
            with SessionLocal.begin() as db:
                purge_accounts(db, account_ids)


if __name__ == "__main__":
    main()
