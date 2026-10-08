"""Real cached embedding model and PostgreSQL, disposable actors/data only."""
import hashlib, json, os, pathlib, time, uuid
from sqlalchemy import func, select
from app.core.db import SessionLocal
from app.core.enums import IndexJobStatus, NoteIndexStatus
from app.core.models import Account, Note, NoteChunk, IndexJob
from app.knowledge.embeddings import embed
from app.knowledge.notes import queue_index
from app.knowledge.indexer import process_job
from app.knowledge.search import rag_evidence_hits
assert os.environ['DATABASE_URL'].endswith('/assistant_security')
assert os.environ['OLLAMA_URL'] == 'http://ollama:11434'
started = time.monotonic()
warm = embed(['隔离向量验证'], timeout=180)
assert len(warm) == 1 and len(warm[0]) == 1024
with SessionLocal.begin() as db:
    users = [Account(email='vector-'+uuid.uuid4().hex+'@example.com', password_hash='unused-synthetic-account') for _ in range(2)]
    db.add_all(users); db.flush()
    notes = [Note(user_id=users[0].id,title='向量旅行计划',body_md='预算3200元。目的地苏州。',version=1,content_version=1),
             Note(user_id=users[1].id,title='账号乙的旅行计划',body_md='预算3200元。目的地苏州。ONLY_B_CANARY',version=1,content_version=1)]
    db.add_all(notes); db.flush()
    user_ids = [user.id for user in users]; note_ids = [note.id for note in notes]
    for note in notes: queue_index(db, note)
with SessionLocal.begin() as db:
    jobs = db.scalars(select(IndexJob).where(IndexJob.note_id.in_(note_ids))).all()
    job_ids = [job.id for job in jobs]
    for job in jobs: job.status = IndexJobStatus.PROCESSING
for job_id in job_ids: process_job(job_id)
checks = []
for repeat in range(1,4):
    for actor, expected in zip(user_ids,note_ids):
        with SessionLocal() as db:
            hits, available = rag_evidence_hits(db,actor,keyword_queries=[],semantic_queries=['预算3200元。目的地苏州。'],per_query_limit=20)
            assert available and any(hit['note_id']==str(expected) for hit in hits)
            assert all(hit['note_id']==str(expected) for hit in hits)
            assert all(hit.get('match_source')=='semantic' for hit in hits)
            checks.append({'repeat':repeat,'actor':'A' if actor==user_ids[0] else 'B','vector_only':True,'semantic_available':available,'own_recalled':True,'foreign_recalled':False,'hits':len(hits)})
with SessionLocal() as db:
    statuses = [db.get(Note,note).index_status == NoteIndexStatus.READY for note in note_ids]
    chunks = db.scalars(select(NoteChunk).where(NoteChunk.note_id.in_(note_ids))).all()
    assert all(statuses) and chunks and all(len(chunk.embedding)==1024 for chunk in chunks)
result={'mode':'real_cached_embedding_real_postgres_synthetic_accounts','model':'qwen3-embedding:0.6b','dimensions':1024,'existing_model_cache_no_download':True,'configured_endpoint':'http://ollama:11434',
        'configured_personal_endpoint_repaired':True,'synthetic_notes_indexed':len(note_ids),'chunks':len(chunks),'checks':checks,'passed':True,'duration_seconds':round(time.monotonic()-started,3)}
pathlib.Path(__file__).with_name('vector-integration-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False))
