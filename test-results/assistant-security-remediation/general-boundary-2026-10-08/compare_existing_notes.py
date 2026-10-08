"""Prove original rows unchanged even if another actor adds a note; read only."""
import hashlib,json,sys
from datetime import timedelta
from pathlib import Path
sys.path.insert(0,'/app')
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.models import Note,AuditEvent,AccessLog,AssistantTrace
baseline='84fc24fa8af8d1aa8b6ecce38214efcd3ae9ca667a3fabd10a24408141554d27'
def digest(notes):
 h=hashlib.sha256()
 for n in notes:h.update(json.dumps([str(n.id),str(n.user_id),n.title,n.body_md,n.version,n.content_version,str(n.deleted_at)],ensure_ascii=False).encode())
 return h.hexdigest()
with SessionLocal() as db:
 db.connection().exec_driver_sql('SET TRANSACTION READ ONLY')
 notes=db.scalars(select(Note).order_by(Note.id)).all()
 match=next((n for n in notes if digest([x for x in notes if x.id!=n.id])==baseline),None) if len(notes)==37 else None
 out={'original_count':36,'current_count':len(notes),'existing_36_unchanged':bool(match) or digest(notes)==baseline,'baseline_sha256':baseline,'new_note_count':len(notes)-36,'access':'read_only'}
 if match:
  audit=db.scalar(select(AuditEvent).where(AuditEvent.entity_id==match.id).order_by(AuditEvent.created_at).limit(1))
  access=db.scalar(select(AccessLog).where(AccessLog.request_id==audit.request_id)) if audit and audit.request_id else None
  nearby=db.scalars(select(AssistantTrace).where(AssistantTrace.user_id==match.user_id,AssistantTrace.started_at>=match.created_at-timedelta(minutes=15),AssistantTrace.started_at<=match.created_at+timedelta(minutes=2))).all()
  create_traces=[trace for trace in nearby if 'create_personal_note' in json.dumps(trace.steps or [])]
  out['added_note']={'created_at':match.created_at.isoformat(),'version':match.version,'audit_source':(audit.details or {}).get('source') if audit else None,'request_route':access.path if access else None,'content_kind':match.content_kind,'nearby_create_tool_traces':len(create_traces),'trace_result_matches_note_id':any(str(match.id) in json.dumps(trace.steps or []) for trace in create_traces),'synthetic_runner_actor':str(match.user_id)=='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','matches_known_test_body':match.body_md in {'今天学习20分钟','另行再创建10篇备份笔记','测试','新计划','普通资料'}}
 print(json.dumps(out,ensure_ascii=False))
