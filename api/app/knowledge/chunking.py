"""Format-aware note segmentation with source-aligned offsets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from app.core.enums import ChunkSource

if TYPE_CHECKING:
    from app.core.models import NoteTextBlock


MAX_CHUNK_LENGTH = 480


@dataclass(frozen=True)
class Segment:
    source: ChunkSource
    start: int
    end: int
    content: str
    location: dict | None = None
    context_prefix: str = ""


@dataclass(frozen=True)
class MarkdownUnit:
    start: int
    end: int
    kind: str
    heading_path: tuple[str, ...]


def split_segment(
    source: ChunkSource,
    raw: str,
    start: int,
    end: int,
    location: dict | None = None,
    context_prefix: str = "",
) -> list[Segment]:
    """Split one source range near a sentence or line boundary when possible."""
    while start < end and raw[start].isspace():
        start += 1
    while end > start and raw[end - 1].isspace():
        end -= 1

    result = []
    while start < end:
        stop = min(end, start + MAX_CHUNK_LENGTH)
        if stop < end:
            candidates = [raw.rfind(mark, start + 300, stop) for mark in ("。", "！", "？", "\n", "；", " ")]
            boundary = max(candidates)
            if boundary > start:
                stop = boundary + 1
        result.append(Segment(source, start, stop, raw[start:stop], location, context_prefix))
        start = stop
        while start < end and raw[start].isspace():
            start += 1
    return result


def _markdown_lines(body: str) -> list[tuple[int, int, str]]:
    """Return each line's source offsets and text without its newline."""
    lines = []
    offset = 0
    for line in body.splitlines(keepends=True):
        text = line.rstrip("\r\n")
        lines.append((offset, offset + len(text), text))
        offset += len(line)
    if not lines and body:
        lines.append((0, len(body), body))
    return lines


def _markdown_units(body: str) -> list[MarkdownUnit]:
    """Parse Markdown structure while retaining offsets into the source body."""
    lines = _markdown_lines(body)
    units: list[MarkdownUnit] = []
    headings: list[str] = []
    heading_re = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
    fence_re = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
    list_re = re.compile(r"^\s{0,3}(?:[-+*]|\d+[.)])\s+")

    def is_table_start(index: int) -> bool:
        if index + 1 >= len(lines) or "|" not in lines[index][2]:
            return False
        cells = lines[index + 1][2].strip().strip("|").split("|")
        return bool(cells) and all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in cells)

    def add(first: int, last: int, kind: str) -> None:
        start, end = lines[first][0], lines[last][1]
        if end > start:
            units.append(MarkdownUnit(start, end, kind, tuple(headings)))

    i = 0
    while i < len(lines):
        text = lines[i][2]
        if not text.strip():
            i += 1
            continue

        heading = heading_re.match(text)
        if heading:
            level = len(heading.group(1))
            headings[:] = headings[: level - 1]
            headings.append(heading.group(2).strip())
            add(i, i, "heading")
            i += 1
            continue

        fence = fence_re.match(text)
        if fence:
            marker = fence.group(1)
            end_index = i + 1
            while end_index < len(lines):
                closing = fence_re.match(lines[end_index][2])
                if closing and closing.group(1)[0] == marker[0] and len(closing.group(1)) >= len(marker):
                    break
                end_index += 1
            last = min(end_index, len(lines) - 1)
            add(i, last, "code")
            i = min(end_index + 1, len(lines))
            continue

        if is_table_start(i):
            end_index = i + 2
            while end_index < len(lines) and "|" in lines[end_index][2] and lines[end_index][2].strip():
                end_index += 1
            add(i, end_index - 1, "table")
            i = end_index
            continue

        if list_re.match(text):
            end_index = i + 1
            while end_index < len(lines):
                candidate = lines[end_index][2]
                if (
                    not candidate.strip()
                    or heading_re.match(candidate)
                    or fence_re.match(candidate)
                    or list_re.match(candidate)
                    or is_table_start(end_index)
                ):
                    break
                end_index += 1
            add(i, end_index - 1, "list")
            i = end_index
            continue

        end_index = i + 1
        while end_index < len(lines):
            candidate = lines[end_index][2]
            if (
                not candidate.strip()
                or heading_re.match(candidate)
                or fence_re.match(candidate)
                or list_re.match(candidate)
                or is_table_start(end_index)
            ):
                break
            end_index += 1
        add(i, end_index - 1, "paragraph")
        i = end_index

    return _merge_short_paragraphs(units)


def _merge_short_paragraphs(units: list[MarkdownUnit]) -> list[MarkdownUnit]:
    packed: list[MarkdownUnit] = []
    for unit in units:
        can_merge = (
            packed
            and unit.kind == "paragraph"
            and packed[-1].kind == "paragraph"
            and unit.heading_path == packed[-1].heading_path
            and unit.end - packed[-1].start <= MAX_CHUNK_LENGTH
        )
        if can_merge:
            previous = packed[-1]
            packed[-1] = MarkdownUnit(previous.start, unit.end, "paragraph", unit.heading_path)
        else:
            packed.append(unit)
    return packed


def _markdown_segments(body: str, base_location: dict | None = None) -> list[Segment]:
    result = []
    for unit in _markdown_units(body):
        location = dict(base_location or {})
        location.update(kind=unit.kind, heading_path=list(unit.heading_path))
        result.extend(
            split_segment(
                ChunkSource.BODY,
                body,
                unit.start,
                unit.end,
                location,
                " / ".join(unit.heading_path),
            )
        )
    return result


def _file_segments(body: str, text_blocks: Sequence[NoteTextBlock]) -> list[Segment]:
    """Segment extracted file blocks without crossing their structural boundaries."""
    result = []
    block_index = 0
    while block_index < len(text_blocks):
        block = text_blocks[block_index]
        start = max(0, block.start_offset)
        end = min(len(body), block.end_offset)
        if start >= end:
            block_index += 1
            continue

        location = dict(block.locator)
        first_paragraph = location.get("paragraph")
        last_paragraph = first_paragraph
        heading_path = location.get("heading_path", [])
        if location.get("kind") == "paragraph":
            next_index = block_index + 1
            while next_index < len(text_blocks):
                following = text_blocks[next_index]
                following_location = following.locator
                following_start = max(0, following.start_offset)
                following_end = min(len(body), following.end_offset)
                if (
                    following_location.get("kind") != "paragraph"
                    or following_location.get("heading_path", []) != heading_path
                    or following_end - start > MAX_CHUNK_LENGTH
                    or following_start < end
                ):
                    break
                end = following_end
                last_paragraph = following_location.get("paragraph", last_paragraph)
                next_index += 1

            if next_index > block_index + 1:
                location.update(kind="paragraph_range", paragraph_start=first_paragraph, paragraph_end=last_paragraph)
                block_index = next_index
            else:
                block_index += 1
        else:
            block_index += 1

        context = " / ".join(heading_path) if isinstance(heading_path, list) else ""
        cursor = start
        for gap in re.finditer(r"\n[ \t]*\n", body[start:end]):
            gap_start = start + gap.start()
            result.extend(split_segment(ChunkSource.BODY, body, cursor, gap_start, location, context))
            cursor = start + gap.end()
        result.extend(split_segment(ChunkSource.BODY, body, cursor, end, location, context))
    return result


def segment_note(title: str, body: str, text_blocks: Sequence[NoteTextBlock] = ()) -> list[Segment]:
    result = [Segment(ChunkSource.TITLE, 0, len(title), title)]
    markdown_block = next((block for block in text_blocks if block.locator.get("kind") == "markdown"), None)
    if not text_blocks or markdown_block is not None:
        return result + _markdown_segments(body, markdown_block.locator if markdown_block else None)
    return result + _file_segments(body, text_blocks)
