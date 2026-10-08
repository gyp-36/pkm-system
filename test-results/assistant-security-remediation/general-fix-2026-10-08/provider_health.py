"""One real-provider request using read-only config; no secrets exported."""
import json,sys
from pathlib import Path
sys.path.insert(0, '/tmp/assistant-remediation/api')
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.models import ModelConnection
from app.assistant.model_connection import chat_model, decrypt_key
with SessionLocal() as db:
    db.connection().exec_driver_sql('SET TRANSACTION READ ONLY')
    row = db.scalar(select(ModelConnection).where(ModelConnection.deleted_at.is_(None)))
    key, model = decrypt_key(row), row.model_name
try:
    response = chat_model(key, model, max_tokens=16).invoke('只回复OK')
    out = {'status':'available' if response.content else 'empty', 'complete_answer':bool(response.content), 'real_provider_attempts':1}
except Exception as exc:
    status=getattr(exc, 'status_code', None)
    out={'status':'unavailable','error_type':type(exc).__name__,'http_status':status,'real_provider_attempts':1,'raw_error_exported':False}
Path(__file__).with_name('provider-health.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
print(json.dumps(out))
