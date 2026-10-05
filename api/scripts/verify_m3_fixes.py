"""Focused M3 regressions for exports, editor callbacks, link drafts, and SSRF."""

from __future__ import annotations

import hashlib
import io
import os
import socket
import uuid
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

import jwt
from docx import Document
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.models import Note, NoteFileVersion
from app.knowledge import m3
from app.knowledge import notes as notes_module
from app.main import app
from app.ops.maintenance import purge_accounts


def checked(client: TestClient, method: str, path: str, expected: int, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code == expected, (method, path, response.status_code, response.text[:500])
    return response.json() if response.content else None


def png_bytes(color: tuple[int, int, int] = (23, 81, 144)) -> bytes:
    image = Image.new("RGB", (3, 2), color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


class _CallbackResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    async def aiter_bytes(self):
        yield UPDATED_DOCX


class _CallbackStream:
    async def __aenter__(self):
        return _CallbackResponse()

    async def __aexit__(self, *_args):
        return False


class _CallbackClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def stream(self, *_args, **_kwargs):
        return _CallbackStream()


UPDATED_DOCX = docx_bytes("saved by office")


def verify_url_security() -> None:
    original_getaddrinfo = socket.getaddrinfo
    socket.getaddrinfo = lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
    ]
    try:
        try:
            m3._resolve_public_addresses("http://public.example/")
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("mixed public/private DNS answers must be rejected")
    finally:
        socket.getaddrinfo = original_getaddrinfo

    pinned: list[tuple] = []

    class _Socket:
        def close(self):
            pass

    original_connect = socket.create_connection
    socket.create_connection = lambda address, *args, **kwargs: (pinned.append(address), _Socket())[1]
    try:
        connection = m3._PinnedHTTPConnection("public.example", 80, ["93.184.216.34"], timeout=1)
        connection.connect()
        connection.close()
    finally:
        socket.create_connection = original_connect
    assert pinned == [("93.184.216.34", 80)], pinned

    original_resolver = m3._resolve_public_addresses
    original_fetch = m3._fetch_pinned_response
    seen: list[str] = []

    def resolver(url: str) -> list[str]:
        host = urlsplit(url).hostname
        if host == "public.example":
            return ["93.184.216.34"]
        raise HTTPException(status_code=422, detail="private redirect blocked")

    def redirect_fetch(url: str):
        seen.append(url)
        resolver(url)
        return 302, "text/html", "http://127.0.0.1/private", b""

    m3._resolve_public_addresses = resolver
    m3._fetch_pinned_response = redirect_fetch
    try:
        try:
            m3.fetch_public_page_source("http://public.example/start", _check_robots=False)
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("redirect to a private address must be rejected")
    finally:
        m3._resolve_public_addresses = original_resolver
        m3._fetch_pinned_response = original_fetch
    assert len(seen) == 2 and urlsplit(seen[-1]).hostname == "127.0.0.1"


def main() -> None:
    verify_url_security()
    account_ids: list[uuid.UUID] = []
    original_file_bytes = m3._file_bytes
    original_async_client = m3.httpx.AsyncClient
    original_resolver = m3._resolve_public_addresses
    UPDATED_DOCX = docx_bytes("saved by office")
    globals()["UPDATED_DOCX"] = UPDATED_DOCX
    try:
        with TestClient(app) as alice, TestClient(app) as bob:
            suffix = uuid.uuid4().hex[:10]
            first = checked(alice, "POST", "/v1/auth/register", 201, json={"email": f"m3fix-a-{suffix}@example.com", "password": "TestPassword123!"})
            second = checked(bob, "POST", "/v1/auth/register", 201, json={"email": f"m3fix-b-{suffix}@example.com", "password": "TestPassword123!"})
            account_ids = [uuid.UUID(first["id"]), uuid.UUID(second["id"])]
            alice_notebook = checked(alice, "POST", "/v1/notebooks", 201, json={"name": "M3 修复验收"})
            bob_notebook = checked(bob, "POST", "/v1/notebooks", 201, json={"name": "隔离验证"})

            image = png_bytes()
            uploaded = checked(alice, "POST", "/v1/notes/upload", 201, files={"file": ("preview.png", image, "image/png")}, data={"sha256": hashlib.sha256(image).hexdigest()}, params={"notebook_id": alice_notebook["id"]})
            note_id = uploaded["id"]
            exported = alice.get(f"/v1/notes/{note_id}/export")
            assert exported.status_code == 200 and exported.content == image
            assert alice.get(f"/v1/notes/{note_id}/file?download=true").content == image
            notebook_zip = alice.get(f"/v1/notebooks/{alice_notebook['id']}/export")
            assert notebook_zip.status_code == 200
            with ZipFile(io.BytesIO(notebook_zip.content)) as archive:
                assert archive.read("M3 修复验收/preview.png") == image

            newer_image = png_bytes((24, 82, 145))
            replaced = alice.put(f"/v1/notes/{note_id}/file?version={uploaded['version']}", files={"file": ("preview.png", newer_image, "image/png")})
            assert replaced.status_code == 200, replaced.text[:300]
            assert alice.get(f"/v1/notes/{note_id}/file?version=1&download=true").content == image
            assert alice.get(f"/v1/notes/{note_id}/export").content == newer_image
            checked(alice, "PUT", f"/v1/notes/{note_id}/file?version={uploaded['version']}", 409, files={"file": ("preview.png", image, "image/png")})

            m3._file_bytes = lambda _row: (_ for _ in ()).throw(HTTPException(status_code=410, detail="missing"))
            checked(alice, "GET", f"/v1/notebooks/{alice_notebook['id']}/export", 502)
            m3._file_bytes = original_file_bytes

            m3._resolve_public_addresses = lambda _url: ["93.184.216.34"]
            url = "https://EXAMPLE.com:443/article?ref=one#section-a"
            draft = checked(alice, "POST", "/v1/link-drafts", 201, json={"url": url, "pasted_text": "saved text"})
            assert draft["source_url"] == "https://example.com/article?ref=one"
            checked(alice, "POST", "/v1/link-drafts", 409, json={"url": "https://example.com/article?ref=one#section-b", "pasted_text": "duplicate"})
            checked(alice, "PATCH", f"/v1/link-drafts/{draft['id']}", 404, json={"notebook_id": bob_notebook["id"]})
            assert checked(alice, "GET", f"/v1/link-drafts/{draft['id']}", 200)["notebook_id"] is None
            set_draft = checked(alice, "PATCH", f"/v1/link-drafts/{draft['id']}", 200, json={"notebook_id": alice_notebook["id"]})
            assert set_draft["notebook_id"] == alice_notebook["id"]
            assert checked(alice, "PATCH", f"/v1/link-drafts/{draft['id']}", 200, json={"notebook_id": None})["notebook_id"] is None
            publish_draft = checked(alice, "POST", "/v1/link-drafts", 201, json={"url": "https://example.com/publish?source=m3#draft", "pasted_text": "M3 publish regression text"})
            published = checked(alice, "POST", f"/v1/link-drafts/{publish_draft['id']}/publish", 201, json={"notebook_id": alice_notebook["id"], "tag_ids": []})
            assert published["source_url"] == "https://example.com/publish?source=m3"
            checked(bob, "GET", f"/v1/notes/{published['id']}", 404)
            checked(alice, "POST", "/v1/link-drafts", 409, json={"url": "https://EXAMPLE.com:443/publish?source=m3#duplicate", "pasted_text": "duplicate published link"})

            office_file = docx_bytes("original document")
            office_note = checked(alice, "POST", "/v1/notes/upload", 201, files={"file": ("office.docx", office_file, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}, data={"sha256": hashlib.sha256(office_file).hexdigest()})
            config = checked(alice, "GET", f"/v1/notes/{office_note['id']}/editor-config", 200)
            assert config["available"] is True
            callback = urlsplit(config["editorConfig"]["callbackUrl"])
            query = parse_qs(callback.query)
            callback_path = callback.path + "?" + callback.query
            document_key = config["document"]["key"]
            secret = os.getenv("ONLYOFFICE_JWT_SECRET") or os.getenv("PKM_FILE_LINK_SECRET")
            assert secret
            token = jwt.encode({"key": document_key}, secret, algorithm="HS256")
            m3.httpx.AsyncClient = _CallbackClient
            payload = {"status": 6, "key": document_key, "url": "http://documentserver/saved.docx"}
            checked(alice, "POST", callback_path, 200, json=payload, headers={"Authorization": f"Bearer {token}"})
            with SessionLocal() as db:
                latest = db.scalar(select(NoteFileVersion).where(NoteFileVersion.note_id == uuid.UUID(office_note["id"])).order_by(NoteFileVersion.version.desc()).limit(1))
                note = db.get(Note, uuid.UUID(office_note["id"]))
                assert latest and latest.version == int(query["file_version"][0]) + 1
                assert note and note.version == int(query["version"][0])
                assert latest.sha256 == hashlib.sha256(UPDATED_DOCX).hexdigest()
            checked(alice, "POST", callback_path, 200, json=payload, headers={"Authorization": f"Bearer {token}"})
            with SessionLocal() as db:
                latest = db.scalar(select(NoteFileVersion).where(NoteFileVersion.note_id == uuid.UUID(office_note["id"])).order_by(NoteFileVersion.version.desc()).limit(1))
                assert latest and latest.sha256 == hashlib.sha256(UPDATED_DOCX).hexdigest()

            print("M3 修复专项通过：S3 单篇导出、ZIP 故障关闭、DNS 固定连接与重定向复核、URL 规范化去重、草稿分类隔离、ONLYOFFICE 旧回调拒绝")
    finally:
        m3._file_bytes = original_file_bytes
        m3.httpx.AsyncClient = original_async_client
        m3._resolve_public_addresses = original_resolver
        if account_ids:
            with SessionLocal.begin() as db:
                purge_accounts(db, account_ids)


if __name__ == "__main__":
    main()
