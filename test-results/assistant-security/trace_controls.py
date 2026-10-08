"""Read-only original trace route controls; never serialize trace contents."""
import json,sys
from pathlib import Path
sys.path.insert(0,'/app')
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.models import AssistantTrace
from app.assistant.tracing import get_trace
rows=[]
with SessionLocal() as db:
 db.connection().exec_driver_sql('SET TRANSACTION READ ONLY')
 t=db.scalar(select(AssistantTrace))
 for rep in range(1,4):
  result=get_trace(t.id,t.user_id,db)
  rows.append({'control':'本人追踪正常访问','rep':rep,'returned_type':type(result).__name__,'pass':isinstance(result,dict),'actual_data_exported':False})
Path('/tmp/assistant-security/trace-controls.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(json.dumps(rows))
