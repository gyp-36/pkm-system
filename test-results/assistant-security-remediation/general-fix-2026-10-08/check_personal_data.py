"""Run in the original container: read-only fingerprints, no content export."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.models import AssistantMessage, ModelConnection, Note

with SessionLocal() as db:
    db.connection().exec_driver_sql("SET TRANSACTION READ ONLY")
    notes = db.scalars(select(Note).order_by(Note.id)).all()
    digest = hashlib.sha256()
    for n in notes:
        digest.update(json.dumps([str(n.id), str(n.user_id), n.title, n.body_md, n.version, n.content_version, str(n.deleted_at)], ensure_ascii=False).encode())
    connections = db.scalars(select(ModelConnection).order_by(ModelConnection.id)).all()
    configs = hashlib.sha256()
    for row in connections:
        configs.update(json.dumps([str(row.id), str(row.user_id), row.model_name, row.credential_ciphertext.hex(), str(row.deleted_at)], ensure_ascii=False).encode())
    messages = db.scalars(select(AssistantMessage).order_by(AssistantMessage.id)).all()
    chats = hashlib.sha256()
    for row in messages:
        chats.update(json.dumps([str(row.id), row.content], ensure_ascii=False, sort_keys=True).encode())
    print(json.dumps({"notes_count": len(notes), "notes_sha256": digest.hexdigest(), "model_configuration_sha256": configs.hexdigest(), "existing_messages_count": len(messages), "existing_messages_sha256": chats.hexdigest(), "access": "read_only"}))
