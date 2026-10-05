"""Resolve same-account image notes referenced by Markdown notes."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.models import MarkdownImageReference, Note
from app.knowledge.file_types import IMAGE_EXTENSIONS


IMAGE_LINK = re.compile(r"!\[((?:\\.|[^\]])*)\]\(/v1/notes/([0-9a-fA-F-]{36})/file\)")
FENCE_START = re.compile(r"^ {0,3}(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
MAX_IMAGE_CONTEXT_PER_SEGMENT = 1500


@dataclass(frozen=True)
class ImageReference:
    start: int
    end: int
    image_note_id: uuid.UUID
    alt_text: str


@dataclass(frozen=True)
class ImageDescription:
    image_note_id: uuid.UUID
    title: str
    caption: str
    note_version: int
    body_md: str


def _mask_line(line: str) -> str:
    return "".join("\n" if char == "\n" else "\r" if char == "\r" else " " for char in line)


def _mask_code(body: str) -> str:
    """Mask fenced and inline code while retaining all source offsets."""
    output: list[str] = []
    fence_char = ""
    fence_size = 0
    for line in body.splitlines(keepends=True):
        visible = line.rstrip("\r\n")
        fence = FENCE_START.match(visible)
        if not fence_char and fence:
            marker = fence.group(1)
            fence_char, fence_size = marker[0], len(marker)
            output.append(_mask_line(line))
            continue
        if fence_char:
            output.append(_mask_line(line))
            if re.match(rf"^ {{0,3}}{re.escape(fence_char)}{{{fence_size},}}[ \t]*$", visible):
                fence_char = ""
                fence_size = 0
            continue
        output.append(INLINE_CODE.sub(lambda match: _mask_line(match.group(0)), line))
    if body and not output:
        return body
    return "".join(output)


def extract_image_references(body: str) -> list[ImageReference]:
    masked = _mask_code(body)
    references = []
    for match in IMAGE_LINK.finditer(masked):
        try:
            image_note_id = uuid.UUID(match.group(2))
        except ValueError:
            continue
        alt_text = re.sub(r"\\([\\\[\]])", r"\1", match.group(1))
        references.append(ImageReference(match.start(), match.end(), image_note_id, alt_text))
    return references


def sync_markdown_image_references(db: Session, note: Note, body: str | None = None) -> list[ImageReference]:
    content = note.body_md if body is None else body
    references = extract_image_references(content)
    db.execute(delete(MarkdownImageReference).where(
        MarkdownImageReference.markdown_note_id == note.id,
        MarkdownImageReference.user_id == note.user_id,
    ))
    db.add_all(
        MarkdownImageReference(
            markdown_note_id=note.id,
            start_offset=reference.start,
            end_offset=reference.end,
            user_id=note.user_id,
            image_note_id=reference.image_note_id,
            alt_text=reference.alt_text,
        )
        for reference in references
    )
    return references


def reference_rows(db: Session, user_id: uuid.UUID, markdown_note_id: uuid.UUID) -> list[MarkdownImageReference]:
    return db.scalars(
        select(MarkdownImageReference)
        .where(
            MarkdownImageReference.user_id == user_id,
            MarkdownImageReference.markdown_note_id == markdown_note_id,
        )
        .order_by(MarkdownImageReference.start_offset)
    ).all()


def descriptions_for_references(
    db: Session,
    user_id: uuid.UUID,
    references: list[MarkdownImageReference],
) -> dict[uuid.UUID, ImageDescription]:
    image_ids = list(dict.fromkeys(reference.image_note_id for reference in references))
    if not image_ids:
        return {}
    images = db.scalars(select(Note).where(
        Note.id.in_(image_ids),
        Note.user_id == user_id,
        Note.deleted_at.is_(None),
        Note.content_kind.in_(IMAGE_EXTENSIONS),
    )).all()
    result = {}
    for image in images:
        caption = image.body_md.strip()
        if caption.startswith("图像描述："):
            caption = caption.removeprefix("图像描述：").strip()
        if caption:
            result[image.id] = ImageDescription(image.id, image.title, caption[:500], image.version, image.body_md)
    return result


def descriptions_for_range(
    db: Session,
    user_id: uuid.UUID,
    markdown_note_id: uuid.UUID,
    start: int,
    end: int,
) -> list[ImageDescription]:
    references = db.scalars(
        select(MarkdownImageReference)
        .where(
            MarkdownImageReference.user_id == user_id,
            MarkdownImageReference.markdown_note_id == markdown_note_id,
            MarkdownImageReference.start_offset < end,
            MarkdownImageReference.end_offset > start,
        )
        .order_by(MarkdownImageReference.start_offset)
    ).all()
    descriptions = descriptions_for_references(db, user_id, references)
    return list({
        description.image_note_id: description
        for reference in references
        if (description := descriptions.get(reference.image_note_id)) is not None
    }.values())


def context_for_range(
    references: list[MarkdownImageReference],
    descriptions: dict[uuid.UUID, ImageDescription],
    start: int,
    end: int,
) -> str:
    contexts = []
    length = 0
    seen: set[uuid.UUID] = set()
    for reference in references:
        if reference.start_offset >= end or reference.end_offset <= start:
            continue
        description = descriptions.get(reference.image_note_id)
        if description is None or description.image_note_id in seen:
            continue
        seen.add(description.image_note_id)
        context = f"图片 {reference.alt_text or description.title}：{description.caption}"
        available = MAX_IMAGE_CONTEXT_PER_SEGMENT - length
        if available <= 0:
            break
        contexts.append(context[:available])
        length += min(len(context), available)
    return "\n".join(contexts)


def invalidate_markdown_references(db: Session, user_id: uuid.UUID, image_note_id: uuid.UUID) -> int:
    """Queue fresh vectors for active Markdown notes that reference an image."""
    rows = db.execute(
        select(Note.id)
        .join(MarkdownImageReference, MarkdownImageReference.markdown_note_id == Note.id)
        .where(
            MarkdownImageReference.user_id == user_id,
            MarkdownImageReference.image_note_id == image_note_id,
            Note.user_id == user_id,
            Note.deleted_at.is_(None),
            Note.content_kind.in_(("markdown", "md")),
        )
        .distinct()
        .order_by(Note.id)
    ).all()
    if not rows:
        return 0
    from app.knowledge.notes import queue_index

    notes = db.scalars(
        select(Note)
        .where(Note.id.in_([row[0] for row in rows]), Note.user_id == user_id, Note.deleted_at.is_(None))
        .order_by(Note.id)
        .with_for_update()
    ).all()
    for note in notes:
        note.content_version += 1
        queue_index(db, note)
    return len(notes)
