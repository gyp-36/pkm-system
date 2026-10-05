"""Disposable lifecycle, history, and audit acceptance check."""

import os
import uuid

import httpx
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.enums import AuditAction, AuditEntityType
from app.ops.maintenance import purge_accounts
from app.core.models import Account, AuditEvent, Note, NoteRevision, Notebook, Tag, UserSession


BASE = os.getenv("M1_TEST_API_URL", "http://api:8000")


def call(client: httpx.Client, method: str, path: str, expected: int, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code == expected, (method, path, response.status_code, response.text[:500])
    return response.json() if response.content else None


def main() -> None:
    account_id = None
    with httpx.Client(base_url=BASE, timeout=30) as client:
        try:
            suffix = uuid.uuid4().hex[:10]
            account = call(client, "POST", "/v1/auth/register", 201, json={"email": f"life-{suffix}@example.com", "password": "TestPassword123!"})
            account_id = uuid.UUID(account["id"])
            notebook = call(client, "POST", "/v1/notebooks", 201, json={"name": "可复用分类"})
            tag = call(client, "POST", "/v1/tags", 201, json={"name": "可复用标签"})
            note = call(client, "POST", "/v1/notes", 201, json={
                "title": "生命周期笔记", "body_md": "敏感正文只应在笔记与修订中", "notebook_id": notebook["id"], "tag_ids": [tag["id"]],
            })
            note_id = uuid.UUID(note["id"])
            note = call(client, "PATCH", f"/v1/notes/{note_id}", 200, json={"version": 1, "body_md": "第二版正文"})
            assert note["version"] == 2
            call(client, "DELETE", f"/v1/notebooks/{notebook['id']}", 204)
            note = call(client, "GET", f"/v1/notes/{note_id}", 200)
            assert note["version"] == 3 and note["notebook_id"] is None
            call(client, "DELETE", f"/v1/tags/{tag['id']}", 204)
            note = call(client, "GET", f"/v1/notes/{note_id}", 200)
            assert note["version"] == 4 and note["tag_ids"] == []
            assert call(client, "POST", "/v1/notebooks", 201, json={"name": "可复用分类"})["id"] != notebook["id"]
            assert call(client, "POST", "/v1/tags", 201, json={"name": "可复用标签"})["id"] != tag["id"]
            call(client, "POST", "/v1/notes", 404, json={"title": "失效分类", "notebook_id": notebook["id"]})
            call(client, "POST", "/v1/notes", 404, json={"title": "失效标签", "tag_ids": [tag["id"]]})

            with SessionLocal() as db:
                revisions = db.scalars(select(NoteRevision).where(NoteRevision.note_id == note_id).order_by(NoteRevision.version)).all()
                assert [row.version for row in revisions] == [1, 2, 3, 4]
                assert revisions[0].body_md == "敏感正文只应在笔记与修订中"
                assert revisions[-1].tag_ids == [] and revisions[-1].notebook_id is None
                events = db.scalars(select(AuditEvent).where(AuditEvent.user_id == account_id)).all()
                assert any(e.action == AuditAction.CREATE and e.entity_type == AuditEntityType.NOTE for e in events)
                assert all("正文" not in str(e.details) and "TestPassword" not in str(e.details) for e in events)
                assert all(e.created_at is not None for e in events)
                account_row = db.get(Account, account_id)
                session_row = db.scalar(select(UserSession).where(UserSession.user_id == account_id))
                notebook_row = db.get(Notebook, uuid.UUID(notebook["id"]))
                tag_row = db.get(Tag, uuid.UUID(tag["id"]))
                assert account_row.created_at <= account_row.updated_at
                assert session_row.created_at <= session_row.updated_at
                assert notebook_row.created_at <= notebook_row.updated_at and notebook_row.deleted_at is not None
                assert tag_row.created_at <= tag_row.updated_at and tag_row.deleted_at is not None

            call(client, "DELETE", f"/v1/notes/{note_id}?version=4", 204)
            call(client, "GET", f"/v1/notes/{note_id}", 404)
            call(client, "DELETE", f"/v1/notes/{note_id}?version=4", 404)
            assert not call(client, "GET", "/v1/search", 200, params={"q": "第二版正文"})["items"]
            assert not call(client, "GET", "/v1/notes", 200)["items"]
            with SessionLocal() as db:
                stored = db.get(Note, note_id)
                assert stored is not None and stored.deleted_at is not None
                assert db.scalar(select(NoteRevision).where(NoteRevision.note_id == note_id)) is not None
                assert any(e.action == AuditAction.DELETE and e.entity_type == AuditEntityType.NOTE for e in db.scalars(select(AuditEvent).where(AuditEvent.user_id == account_id)))
            print("生命周期、版本记录、审计和软删除检查均已通过")
        finally:
            if account_id is not None:
                with SessionLocal.begin() as db:
                    purge_accounts(db, [account_id])


if __name__ == "__main__":
    main()
