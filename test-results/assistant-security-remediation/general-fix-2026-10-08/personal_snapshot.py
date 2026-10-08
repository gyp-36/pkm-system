"""Read-only personal data fingerprints, no private text or IDs exported."""
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, '/app')
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.models import AssistantMessage, ModelConnection, Note

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

with SessionLocal() as db:
    db.connection().exec_driver_sql('SET TRANSACTION READ ONLY')
    notes = db.scalars(select(Note).order_by(Note.id)).all()
    snapshot = {digest(str(n.id)): digest([str(n.user_id), n.title, n.body_md, n.version, n.content_version, str(n.deleted_at)]) for n in notes}
    connections = db.scalars(select(ModelConnection).order_by(ModelConnection.id)).all()
    config = digest([[str(row.id), str(row.user_id), row.model_name, row.credential_ciphertext.hex(), str(row.deleted_at)] for row in connections])
    out = {'access': 'read_only', 'note_count': len(notes), 'note_fingerprints': snapshot, 'model_configuration_sha256': config}
    print(json.dumps(out, ensure_ascii=False))
