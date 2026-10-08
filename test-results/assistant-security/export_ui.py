"""Export only the five explicitly created security-test conversations, read-only."""
import hashlib,json,uuid,sys
sys.path.insert(0,"/app")
from pathlib import Path
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.models import AssistantConversation,AssistantMessage,AssistantTrace,Note
IDS=['77788a03-a1b4-478c-b3f5-d0e4197ade50','94a8b89e-0d47-4a23-8748-42306144740b','7389561d-7838-4324-9e21-d14b14d1c07e','14baf29f-7a1e-436f-91fd-91a3b68220b0','a64a40c6-8f0a-486b-8998-7c8c18ce2492']
with SessionLocal() as db:
 db.connection().exec_driver_sql('SET TRANSACTION READ ONLY')
 conversations=[]
 for ident in IDS:
  cid=uuid.UUID(ident);c=db.get(AssistantConversation,cid)
  if c is None:continue
  messages=db.scalars(select(AssistantMessage).where(AssistantMessage.conversation_id==cid,AssistantMessage.user_id==c.user_id).order_by(AssistantMessage.created_at)).all()
  assert messages and messages[0].content['text'].startswith('安全测试')
  traces=db.scalars(select(AssistantTrace).where(AssistantTrace.conversation_id==cid,AssistantTrace.user_id==c.user_id)).all()
  model_steps=[step for t in traces for step in (t.steps or []) if step.get('kind')=='model']
  trace_summary={'requests':len(traces),'model_calls':len(model_steps),'tokens':sum(step.get('summary',{}).get('usage',{}).get('total_tokens',0) for step in model_steps),'duration_ms':sum(t.duration_ms or 0 for t in traces),'tool_steps':sum(step.get('kind')=='tool' for t in traces for step in (t.steps or []))}
  conversations.append({'conversation_id':ident,'trace_summary':trace_summary,'messages':[{'role':m.role,'content':m.content} for m in messages]})
 notes=db.scalars(select(Note).order_by(Note.id)).all();h=hashlib.sha256()
 for n in notes:h.update(json.dumps([str(n.id),str(n.user_id),n.title,n.body_md,n.version,n.content_version,str(n.deleted_at)],ensure_ascii=False).encode())
 out={'mode':'real_database_read_only','conversations':conversations,'notes_count':len(notes),'notes_sha256':h.hexdigest(),'ui_4_persisted_4':conversations[-1]['messages'][-1]['content']['answer']=='4'}
def redact(value):
 if isinstance(value,list):return [redact(x) for x in value]
 if isinstance(value,dict):return {k:('existing-note-'+hashlib.sha256(str(v).encode()).hexdigest()[:10] if k=='note_id' else redact(v)) for k,v in value.items()}
 return value
out=redact(out)
Path('/tmp/assistant-security/ui-persisted.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in out.items() if k!='conversations'}))
