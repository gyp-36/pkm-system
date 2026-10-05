"""Account-scoped literal keyword and current-version vector retrieval."""

import re
import uuid

import httpx
from fastapi import APIRouter, Query
from sqlalchemy import case, or_, select

from app.auth.auth import Db, UserId
from app.core.enums import ChunkSource
from app.knowledge.embeddings import embed
from app.core.models import Note, NoteChunk, NoteTag, NoteTextBlock


router = APIRouter(prefix="/v1", tags=["search"])
MAX_DISTANCE = 0.48  # 初始阈值取保守值，后续根据固定评测集进行校准。


def filters(query, user_id: uuid.UUID, notebook_id: uuid.UUID | None, tag_id: uuid.UUID | None):
    query = query.where(Note.user_id == user_id, Note.deleted_at.is_(None))
    if notebook_id is not None:
        query = query.where(Note.notebook_id == notebook_id)
    if tag_id is not None:
        query = query.where(Note.id.in_(select(NoteTag.note_id).where(NoteTag.user_id == user_id, NoteTag.tag_id == tag_id)))
    return query


def hit(note: Note, source: str, start: int, end: int, snippet: str, location: dict | None = None) -> dict:
    return {
        "note_id": str(note.id),
        "title": note.title,
        "notebook_id": str(note.notebook_id) if note.notebook_id else None,
        "version": note.version,
        "source_field": source,
        "content_kind": note.content_kind,
        "location": location,
        "start_offset": start,
        "end_offset": end,
        "snippet": snippet,
        "updated_at": note.updated_at.isoformat(),
    }


def keyword_hits(
    db: Db,
    user_id: uuid.UUID,
    q: str,
    notebook_id: uuid.UUID | None,
    tag_id: uuid.UUID | None,
    *,
    limit: int = 60,
) -> list[dict]:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    title_match = Note.title.ilike(pattern, escape="\\")
    query = filters(select(Note), user_id, notebook_id, tag_id).where(
        or_(Note.title.ilike(pattern, escape="\\"), Note.body_md.ilike(pattern, escape="\\"))
    ).order_by(case((title_match, 0), else_=1), Note.updated_at.desc()).limit(limit)
    results = []
    for note in db.scalars(query):
        body_match = re.search(re.escape(q), note.body_md, flags=re.IGNORECASE)
        if body_match:
            start = max(0, body_match.start() - 80)
            end = min(len(note.body_md), body_match.end() + 120)
            block = db.scalar(select(NoteTextBlock).where(NoteTextBlock.note_id == note.id, NoteTextBlock.user_id == user_id, NoteTextBlock.content_version == note.content_version, NoteTextBlock.start_offset <= body_match.start(), NoteTextBlock.end_offset >= body_match.end()).order_by(NoteTextBlock.ordinal).limit(1))
            results.append(hit(note, "body", start, end, note.body_md[start:end], block.locator if block else None))
        elif note.body_md:
            # A title-only hit identifies a relevant note but is weak answer evidence.
            # Return its first source-aligned body block so the agent can judge usefulness.
            block = db.scalar(
                select(NoteTextBlock)
                .where(
                    NoteTextBlock.note_id == note.id,
                    NoteTextBlock.user_id == user_id,
                    NoteTextBlock.content_version == note.content_version,
                )
                .order_by(NoteTextBlock.ordinal)
                .limit(1)
            )
            start = max(0, block.start_offset) if block is not None else 0
            end = min(len(note.body_md), block.end_offset) if block is not None else min(len(note.body_md), 240)
            if end > start:
                results.append(hit(note, "body", start, end, note.body_md[start:end], block.locator if block else None))
            else:
                results.append(hit(note, "title", 0, len(note.title), note.title))
        else:
            results.append(hit(note, "title", 0, len(note.title), note.title))
    return results


def vector_hits(
    db: Db,
    user_id: uuid.UUID,
    q: str,
    notebook_id: uuid.UUID | None,
    tag_id: uuid.UUID | None,
    *,
    timeout: float = 180.0,
    limit: int = 60,
    dedupe_notes: bool = True,
    query_vector: list[float] | None = None,
) -> list[dict]:
    vector = query_vector if query_vector is not None else embed([q], timeout=timeout)[0]
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
    ).order_by(distance).limit(limit)
    results = []
    seen = set()
    for chunk, note, _distance in db.execute(query):
        if dedupe_notes and note.id in seen:
            continue
        seen.add(note.id)
        results.append(hit(note, ChunkSource(chunk.source).name.lower(), chunk.start_offset, chunk.end_offset, chunk.content, chunk.location))
    return results


def rag_evidence_hits(
    db: Db,
    user_id: uuid.UUID,
    *,
    keyword_queries: list[str],
    semantic_queries: list[str],
    per_query_limit: int = 20,
    notebook_id: uuid.UUID | None = None,
    tag_id: uuid.UUID | None = None,
) -> tuple[list[dict], bool]:
    """Return fused passage evidence and whether vector retrieval completed."""
    candidate_map: dict[tuple, dict] = {}
    keyword_ranks: dict[tuple, int] = {}
    semantic_ranks: dict[tuple, int] = {}

    def evidence_key(candidate: dict) -> tuple:
        return (
            candidate["note_id"],
            candidate["version"],
            candidate["source_field"],
            candidate["start_offset"],
            candidate["end_offset"],
        )

    def record(candidates: list[dict], ranks: dict[tuple, int]) -> None:
        for rank, candidate in enumerate(candidates, start=1):
            key = evidence_key(candidate)
            candidate_map.setdefault(key, candidate)
            previous = ranks.get(key)
            if previous is None or rank < previous:
                ranks[key] = rank

    for query in keyword_queries:
        record(
            keyword_hits(db, user_id, query, notebook_id, tag_id, limit=per_query_limit),
            keyword_ranks,
        )

    semantic_available = True
    try:
        vectors = embed(semantic_queries, timeout=20.0) if semantic_queries else []
        for query, vector in zip(semantic_queries, vectors, strict=True):
            record(
                vector_hits(
                    db,
                    user_id,
                    query,
                    notebook_id,
                    tag_id,
                    limit=per_query_limit,
                    dedupe_notes=False,
                    query_vector=vector,
                ),
                semantic_ranks,
            )
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        semantic_available = False
        semantic_ranks.clear()
        candidate_map = {key: value for key, value in candidate_map.items() if key in keyword_ranks}

    ranked = []
    for key, candidate in candidate_map.items():
        keyword_rank = keyword_ranks.get(key)
        semantic_rank = semantic_ranks.get(key)
        score = (1 / (60 + keyword_rank) if keyword_rank is not None else 0.0) + (
            1 / (60 + semantic_rank) if semantic_rank is not None else 0.0
        )
        ranked.append({
            **candidate,
            "score": score,
            "match_source": (
                "both" if keyword_rank is not None and semantic_rank is not None
                else "keyword" if keyword_rank is not None
                else "semantic"
            ),
        })
    ranked.sort(key=lambda item: (item["score"], item["updated_at"]), reverse=True)
    return ranked, semantic_available


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
