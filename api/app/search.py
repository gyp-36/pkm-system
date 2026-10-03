"""Account-scoped literal keyword and current-version vector retrieval."""

import re
import uuid

import httpx
from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from app.auth import Db, UserId
from app.enums import ChunkSource
from app.embeddings import embed
from app.models import Note, NoteChunk, NoteTag


router = APIRouter(prefix="/v1", tags=["search"])
MAX_DISTANCE = 0.48  # Conservative initial cutoff; calibrate against the fixed evaluation set.


def filters(query, user_id: uuid.UUID, notebook_id: uuid.UUID | None, tag_id: uuid.UUID | None):
    query = query.where(Note.user_id == user_id, Note.deleted_at.is_(None))
    if notebook_id is not None:
        query = query.where(Note.notebook_id == notebook_id)
    if tag_id is not None:
        query = query.where(Note.id.in_(select(NoteTag.note_id).where(NoteTag.user_id == user_id, NoteTag.tag_id == tag_id)))
    return query


def hit(note: Note, source: str, start: int, end: int, snippet: str) -> dict:
    return {
        "note_id": str(note.id),
        "title": note.title,
        "notebook_id": str(note.notebook_id) if note.notebook_id else None,
        "version": note.version,
        "source_field": source,
        "start_offset": start,
        "end_offset": end,
        "snippet": snippet,
        "updated_at": note.updated_at.isoformat(),
    }


def keyword_hits(db: Db, user_id: uuid.UUID, q: str, notebook_id: uuid.UUID | None, tag_id: uuid.UUID | None) -> list[dict]:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    query = filters(select(Note), user_id, notebook_id, tag_id).where(
        or_(Note.title.ilike(pattern, escape="\\"), Note.body_md.ilike(pattern, escape="\\"))
    ).order_by(Note.updated_at.desc()).limit(60)
    results = []
    for note in db.scalars(query):
        body_match = re.search(re.escape(q), note.body_md, flags=re.IGNORECASE)
        if body_match:
            start = max(0, body_match.start() - 80)
            end = min(len(note.body_md), body_match.end() + 120)
            results.append(hit(note, "body", start, end, note.body_md[start:end]))
        else:
            results.append(hit(note, "title", 0, len(note.title), note.title))
    return results


def vector_hits(db: Db, user_id: uuid.UUID, q: str, notebook_id: uuid.UUID | None, tag_id: uuid.UUID | None, *, timeout: float = 180.0) -> list[dict]:
    vector = embed([q], timeout=timeout)[0]
    distance = NoteChunk.embedding.cosine_distance(vector)
    query = filters(
        select(NoteChunk, Note, distance.label("distance"))
        .join(Note, Note.id == NoteChunk.note_id)
        .where(
            NoteChunk.user_id == user_id,
            NoteChunk.note_version == Note.content_version,
            NoteChunk.embedding.is_not(None),
            distance <= MAX_DISTANCE,
        ),
        user_id,
        notebook_id,
        tag_id,
    ).order_by(distance).limit(60)
    results = []
    seen = set()
    for chunk, note, _distance in db.execute(query):
        if note.id in seen:
            continue
        seen.add(note.id)
        results.append(hit(note, ChunkSource(chunk.source).name.lower(), chunk.start_offset, chunk.end_offset, chunk.content))
    return results


def search_notes(
    db: Db,
    user_id: uuid.UUID,
    q: str,
    *,
    mode: str = "keyword",
    notebook_id: uuid.UUID | None = None,
    tag_id: uuid.UUID | None = None,
    limit: int = 20,
) -> dict:
    q = q.strip()
    if not q:
        return {"items": [], "semantic_status": "not_requested" if mode == "keyword" else "ready"}
    keywords = keyword_hits(db, user_id, q, notebook_id, tag_id)
    semantic: list[dict] = []
    semantic_status = "not_requested"
    if mode == "hybrid":
        try:
            semantic = vector_hits(db, user_id, q, notebook_id, tag_id)
            semantic_status = "ready"
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            semantic_status = "unavailable"

    ranked: dict[str, dict] = {}
    for origin, candidates in (("keyword", keywords), ("semantic", semantic)):
        for rank, candidate in enumerate(candidates, start=1):
            key = candidate["note_id"]
            score = 1 / (60 + rank)
            if key not in ranked:
                ranked[key] = {**candidate, "score": score, "match_source": origin}
            else:
                ranked[key]["score"] += score
                ranked[key]["match_source"] = "both"
    items = sorted(ranked.values(), key=lambda item: (item["score"], item["updated_at"]), reverse=True)[:limit]
    return {"items": items, "semantic_status": semantic_status}


@router.get("/search")
def search(
    db: Db,
    user_id: UserId,
    q: str = Query(min_length=1, max_length=150),
    mode: str = Query(default="keyword", pattern="^(keyword|hybrid)$"),
    notebook_id: uuid.UUID | None = None,
    tag_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=50),
) -> dict:
    return search_notes(
        db, user_id, q, mode=mode, notebook_id=notebook_id, tag_id=tag_id, limit=limit
    )
