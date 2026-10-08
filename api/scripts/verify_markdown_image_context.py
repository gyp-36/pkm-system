"""Verify Markdown image descriptions, citations, and dependency reindexing."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.assistant.assistant import Evidence
from app.core.db import SessionLocal
from app.core.enums import IndexJobStatus, NoteIndexStatus
from app.core.models import Account, IndexJob, MarkdownImageReference, Note, NoteChunk
from app.knowledge import indexer
from app.knowledge.markdown_images import (
    descriptions_for_range,
    extract_image_references,
    invalidate_markdown_references,
)
from app.knowledge.notes import delete_note, get_image_references, queue_index
from app.knowledge.archive import restore_archived_note
from app.ops.maintenance import purge_accounts


def process_pending(note_id: uuid.UUID, user_id: uuid.UUID) -> None:
    with SessionLocal.begin() as db:
        job = db.scalar(
            select(IndexJob)
            .where(
                IndexJob.note_id == note_id,
                IndexJob.user_id == user_id,
                IndexJob.status == IndexJobStatus.PENDING,
            )
            .order_by(IndexJob.created_at.desc())
            .with_for_update()
            .limit(1)
        )
        assert job is not None, "expected a queued image-context reindex"
        job.status = IndexJobStatus.PROCESSING
        job_id = job.id
    indexer.process_job(job_id)


def main() -> None:
    suffix = uuid.uuid4().hex
    user_id = uuid.uuid4()
    original_embed = indexer.embed
    embedded_texts: list[str] = []
    account_ids: list[uuid.UUID] = []
    try:
        with SessionLocal.begin() as db:
            account = Account(id=user_id, email=f"image-context-{suffix}@example.com", password_hash="test")
            db.add(account)
            db.flush()
            account_ids.append(user_id)

            image = Note(
                user_id=user_id,
                title="蓝色陶瓷杯",
                body_md="图像描述：一只蓝色陶瓷杯摆在木桌上。",
                content_kind="png",
                version=1,
                content_version=1,
                index_status=NoteIndexStatus.READY,
            )
            db.add(image)
            db.flush()
            image_id = image.id

            foreign_user_id = uuid.uuid4()
            foreign = Account(id=foreign_user_id, email=f"image-context-other-{suffix}@example.com", password_hash="test")
            db.add(foreign)
            db.flush()
            account_ids.append(foreign_user_id)
            foreign_image = Note(
                user_id=foreign_user_id,
                title="其他账户图片",
                body_md="图像描述：不应泄漏的描述。",
                content_kind="png",
                version=1,
                content_version=1,
                index_status=NoteIndexStatus.READY,
            )
            db.add(foreign_image)
            db.flush()
            foreign_image_id = foreign_image.id

            body = (
                f"会议记录提到：![杯子](/v1/notes/{image_id}/file)\n\n"
                f"`![行内代码](/v1/notes/{foreign_image_id}/file)`\n\n"
                f"```md\n![代码块](/v1/notes/{foreign_image_id}/file)\n```\n\n"
                f"![外部图片](https://example.com/image.png)"
            )
            parsed = extract_image_references(body)
            assert len(parsed) == 1 and parsed[0].image_note_id == image_id and parsed[0].alt_text == "杯子", parsed
            markdown = Note(
                user_id=user_id,
                title="讨论记录",
                body_md=body,
                content_kind="md",
                version=1,
                content_version=1,
                index_status=NoteIndexStatus.PENDING,
            )
            db.add(markdown)
            db.flush()
            markdown_id = markdown.id
            queue_index(db, markdown)

            refs = db.scalars(select(MarkdownImageReference).where(
                MarkdownImageReference.user_id == user_id,
                MarkdownImageReference.markdown_note_id == markdown_id,
            )).all()
            assert len(refs) == 1 and refs[0].image_note_id == image_id
            warning = get_image_references(image_id, db, user_id)
            assert warning["total_notes"] == 1 and warning["total_references"] == 1, warning
            assert descriptions_for_range(db, user_id, markdown_id, refs[0].start_offset, refs[0].end_offset)[0].caption == "一只蓝色陶瓷杯摆在木桌上。"
            foreign_offset = body.index(str(foreign_image_id))
            db.add(MarkdownImageReference(
                markdown_note_id=markdown_id,
                start_offset=foreign_offset,
                end_offset=foreign_offset + 1,
                user_id=user_id,
                image_note_id=foreign_image_id,
                alt_text="不应泄漏",
            ))
            db.flush()
            assert not descriptions_for_range(db, user_id, markdown_id, foreign_offset, foreign_offset + 1)

        def fake_embed(texts: list[str], **_kwargs):
            embedded_texts.extend(texts)
            return [[0.0] * 1024 for _ in texts]

        indexer.embed = fake_embed
        process_pending(markdown_id, user_id)
        assert any("一只蓝色陶瓷杯摆在木桌上。" in text for text in embedded_texts), embedded_texts
        with SessionLocal() as db:
            markdown = db.get(Note, markdown_id)
            chunks = db.scalars(select(NoteChunk).where(
                NoteChunk.note_id == markdown_id,
                NoteChunk.user_id == user_id,
                NoteChunk.note_version == markdown.content_version,
            )).all()
            assert chunks and any("![杯子]" in chunk.content for chunk in chunks)
            assert all("一只蓝色陶瓷杯摆在木桌上。" not in chunk.content for chunk in chunks)
            description = descriptions_for_range(db, user_id, markdown_id, 0, len(markdown.body_md))[0]

        evidence = Evidence(user_id)
        image_citation_id = evidence.add_image_description(description)
        assert image_citation_id is not None
        verified = evidence.verified(f"[{image_citation_id}]")
        assert len(verified) == 1 and verified[0]["note_id"] == str(image_id), verified

        embedded_texts.clear()
        with SessionLocal.begin() as db:
            image = db.get(Note, image_id)
            image.body_md = "图像描述：杯中装有热茶，旁边放着一本书。"
            image.version += 1
            image.content_version += 1
            invalidate_markdown_references(db, user_id, image_id)
        process_pending(markdown_id, user_id)
        assert any("杯中装有热茶" in text for text in embedded_texts), embedded_texts
        assert not any("蓝色陶瓷杯摆在木桌上" in text for text in embedded_texts), embedded_texts

        embedded_texts.clear()
        with SessionLocal() as db:
            image = db.get(Note, image_id)
            delete_note(image_id, db, user_id, image.version)
        process_pending(markdown_id, user_id)
        assert not any("杯中装有热茶" in text for text in embedded_texts), embedded_texts

        embedded_texts.clear()
        with SessionLocal() as db:
            restore_archived_note(image_id, db, user_id)
        process_pending(markdown_id, user_id)
        assert any("杯中装有热茶" in text for text in embedded_texts), embedded_texts

        with SessionLocal.begin() as db:
            markdown = db.get(Note, markdown_id)
            markdown.body_md = "这份记录已不再附图。"
            markdown.version += 1
            markdown.content_version += 1
            queue_index(db, markdown)
            assert get_image_references(image_id, db, user_id)["total_references"] == 0
        print("Markdown image context: parsing, vector enrichment, citations, isolation, archive/restore, and reference removal passed")
    finally:
        indexer.embed = original_embed
        if account_ids:
            with SessionLocal.begin() as db:
                purge_accounts(db, account_ids)


if __name__ == "__main__":
    main()
