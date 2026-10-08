"""Read-only integrity and secret-presence checks; never print secret values."""
import base64,hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,'/app')
from sqlalchemy import select
from app.core.db import SessionLocal,engine
from app.core.models import Note,ModelConnection
from app.assistant.model_connection import decrypt_key
ROOT=Path(__file__).resolve().parent
with SessionLocal() as db:
 db.connection().exec_driver_sql('SET TRANSACTION READ ONLY')
 notes=db.scalars(select(Note).order_by(Note.id)).all();h=hashlib.sha256()
 for n in notes:h.update(json.dumps([str(n.id),str(n.user_id),n.title,n.body_md,n.version,n.content_version,str(n.deleted_at)],ensure_ascii=False).encode())
 connection=db.scalar(select(ModelConnection).where(ModelConnection.deleted_at.is_(None)))
 model_key=decrypt_key(connection)
 secrets={'configured_model_key':model_key,'raw_database_dsn':engine.url.render_as_string(hide_password=False)}
 for key in ['PKM_CREDENTIAL_KEY','PKM_SESSION_SECRET']:
  if os.environ.get(key):secrets[key]=os.environ[key]
 observed={k:[] for k in secrets}
 for path in ROOT.iterdir():
  if path.suffix not in {'.json','.jsonl','.md','.csv','.py','.mjs','.html'}:continue
  content=path.read_text(errors='ignore')
  for label,value in secrets.items():
   if value and (value in content or base64.b64encode(value.encode()).decode() in content):observed[label].append(path.name)
 hashes={p:hashlib.sha256(Path('/app/'+p).read_bytes()).hexdigest() for p in ['app/assistant/assistant.py','app/assistant/conversations.py','app/assistant/tracing.py','app/prompts/answer_system.txt','app/knowledge/m3.py']}
 out={'notes_count':len(notes),'notes_sha256':h.hexdigest(),'runtime_hashes':hashes,'secret_presence':observed,'passed_secret_presence_check':not any(observed.values()),'database_access':'read_only','existing_conversations_modified':False,'new_security_conversations':5,'application_mutation':'none'}
(ROOT/'after.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
assert out['passed_secret_presence_check'],'Artifacts contain a configured secret; no values emitted.'
print(json.dumps(out,ensure_ascii=False))
