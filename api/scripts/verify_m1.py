"""Disposable two-account M1 acceptance check against the running Compose API."""

import io
import os
import time
import uuid
import zipfile

import httpx
from sqlalchemy import select

from app.core.db import SessionLocal
from app.ops.maintenance import purge_accounts
from app.core.models import NoteChunk


BASE = os.getenv("M1_TEST_API_URL", "http://api:8000")


def call(client: httpx.Client, method: str, path: str, expected: int, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code == expected, (method, path, response.status_code, response.text[:600])
    return response.json() if response.content else None


def main() -> None:
    suffix = uuid.uuid4().hex[:10]
    account_ids: list[uuid.UUID] = []
    with httpx.Client(base_url=BASE, timeout=90) as alice, httpx.Client(base_url=BASE, timeout=90) as bob:
        try:
            a = call(alice, "POST", "/v1/auth/register", 201, json={"email": f"m1a-{suffix}@example.com", "password": "TestPassword123!"})
            account_ids.append(uuid.UUID(a["id"]))
            b = call(bob, "POST", "/v1/auth/register", 201, json={"email": f"m1b-{suffix}@example.com", "password": "TestPassword123!"})
            account_ids.append(uuid.UUID(b["id"]))
            notebook = call(alice, "POST", "/v1/notebooks", 201, json={"name": "学习"})
            tag = call(alice, "POST", "/v1/tags", 201, json={"name": "方法"})
            assert call(alice, "GET", f"/v1/notebooks/{notebook['id']}", 200) == notebook
            assert call(alice, "GET", f"/v1/tags/{tag['id']}", 200) == tag
            call(bob, "GET", f"/v1/notebooks/{notebook['id']}", 404)
            call(bob, "GET", f"/v1/tags/{tag['id']}", 404)
            call(alice, "PATCH", f"/v1/notebooks/{notebook['id']}", 200, json={"name": "学习资料"})
            call(alice, "PATCH", f"/v1/tags/{tag['id']}", 200, json={"name": "学习方法"})
            assert call(alice, "GET", f"/v1/notebooks/{notebook['id']}", 200)["name"] == "学习资料"
            assert call(alice, "GET", f"/v1/tags/{tag['id']}", 200)["name"] == "学习方法"
            bob_notebook = call(bob, "POST", "/v1/notebooks", 201, json={"name": "私人"})
            note = call(alice, "POST", "/v1/notes", 201, json={
                "title": "专注与休息",
                "body_md": "😀 番茄钟帮助我保持专注。每工作二十五分钟，休息五分钟。",
                "notebook_id": notebook["id"],
                "tag_ids": [tag["id"]],
            })
            bob_note = call(bob, "POST", "/v1/notes", 201, json={"title": "秘密", "body_md": "专属内容蓝色海洋"})
            call(bob, "GET", f"/v1/notes/{note['id']}", 404)
            call(bob, "GET", f"/v1/notes/{note['id']}/export", 404)
            call(bob, "PATCH", f"/v1/notes/{note['id']}", 404, json={"version": 1, "title": "越权"})
            call(alice, "POST", "/v1/notes", 404, json={"title": "越权分类", "notebook_id": bob_notebook["id"]})
            call(alice, "POST", "/v1/notes", 404, json={"title": "越权标签", "tag_ids": [str(uuid.uuid4())]})
            single_export = alice.get(f"/v1/notes/{note['id']}/export")
            assert single_export.status_code == 200, single_export.text[:300]
            assert single_export.headers["content-type"].startswith("text/markdown")
            # Current M3 export contract preserves note content without injected metadata.
            assert single_export.text == note["body_md"]
            all_export = alice.get("/v1/notes/export")
            assert all_export.status_code == 200, all_export.text[:300]
            assert all_export.headers["content-type"].startswith("application/zip")
            with zipfile.ZipFile(io.BytesIO(all_export.content)) as archive:
                exported_paths = [path for path in archive.namelist() if path.endswith(".md") and path != "README.md"]
                assert len(exported_paths) == 1, exported_paths
                exported_markdown = archive.read(exported_paths[0]).decode("utf-8")
                assert note["body_md"] in exported_markdown
                assert bob_note["body_md"] not in exported_markdown
            assert not call(alice, "GET", "/v1/search", 200, params={"q": "蓝色海洋", "mode": "keyword"})["items"]
            assert call(alice, "GET", "/v1/search", 200, params={"q": "番茄钟", "mode": "keyword"})["items"][0]["note_id"] == note["id"]
            assert call(alice, "GET", "/v1/notes", 200, params={"notebook_id": notebook["id"], "tag_id": tag["id"]})["items"][0]["id"] == note["id"]
            assert not call(alice, "GET", "/v1/notes", 200, params={"notebook_id": bob_notebook["id"]})["items"]
            call(alice, "PATCH", f"/v1/notes/{note['id']}", 409, json={"version": 999, "title": "冲突"})

            for _ in range(60):
                current = call(alice, "GET", f"/v1/notes/{note['id']}", 200)
                if current["index_status"] == "ready":
                    break
                time.sleep(2)
            assert current["index_status"] == "ready", current
            hybrid = call(alice, "GET", "/v1/search", 200, params={"q": "如何分段工作并定时休息", "mode": "hybrid"})
            assert hybrid["semantic_status"] == "ready", hybrid
            assert any(item["note_id"] == note["id"] for item in hybrid["items"]), hybrid
            print("语义同义词命中：", [(item["title"], item["match_source"]) for item in hybrid["items"]])

            updated = call(alice, "PATCH", f"/v1/notes/{note['id']}", 200, json={"version": current["version"], "body_md": "😀 用间隔复习法巩固知识。"})
            assert updated["version"] == 2
            assert not call(alice, "GET", "/v1/search", 200, params={"q": "番茄钟", "mode": "keyword"})["items"]
            assert call(alice, "GET", "/v1/search", 200, params={"q": "间隔复习法", "mode": "keyword"})["items"][0]["note_id"] == note["id"]
            for _ in range(60):
                current = call(alice, "GET", f"/v1/notes/{note['id']}", 200)
                if current["index_status"] == "ready":
                    break
                time.sleep(2)
            assert current["index_status"] == "ready", current
            with SessionLocal() as db:
                chunks = db.scalars(select(NoteChunk).where(NoteChunk.note_id == uuid.UUID(note["id"]))).all()
                assert chunks and all(chunk.note_version == 2 for chunk in chunks)
                assert all("番茄钟" not in chunk.content for chunk in chunks)
            call(alice, "DELETE", f"/v1/notebooks/{notebook['id']}", 204)
            call(alice, "DELETE", f"/v1/tags/{tag['id']}", 204)
            call(alice, "GET", f"/v1/notebooks/{notebook['id']}", 404)
            call(alice, "GET", f"/v1/tags/{tag['id']}", 404)
            current = call(alice, "GET", f"/v1/notes/{note['id']}", 200)
            assert current["notebook_id"] is None and not current["tag_ids"]
            call(alice, "DELETE", f"/v1/notes/{note['id']}?version={current['version']}", 204)
            call(alice, "GET", f"/v1/notes/{note['id']}", 404)
            call(alice, "GET", f"/v1/notes/{note['id']}/export", 404)
            with zipfile.ZipFile(io.BytesIO(alice.get("/v1/notes/export").content)) as archive:
                assert not [path for path in archive.namelist() if path.endswith(".md") and path != "README.md"]
            assert not call(alice, "GET", "/v1/search", 200, params={"q": "间隔复习法", "mode": "hybrid"})["items"]
            call(alice, "POST", "/v1/auth/logout", 204)
            call(alice, "GET", "/v1/auth/me", 401)
            print("M1 API 验收检查均已通过")
        finally:
            with SessionLocal.begin() as db:
                purge_accounts(db, account_ids)


if __name__ == "__main__":
    main()
