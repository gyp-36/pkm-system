"""Read-only secret presence check, never exports credential values."""
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app")
from sqlalchemy import select
from app.core.db import SessionLocal, engine
from app.core.models import ModelConnection
from app.assistant.model_connection import decrypt_key

root = Path(__file__).parent
with SessionLocal() as db:
    db.connection().exec_driver_sql("SET TRANSACTION READ ONLY")
    values = [engine.url.render_as_string(hide_password=False)]
    values.extend(os.environ[k] for k in ("PKM_CREDENTIAL_KEY", "PKM_SESSION_SECRET") if os.environ.get(k))
    for connection in db.scalars(select(ModelConnection).where(ModelConnection.deleted_at.is_(None))):
        values.append(decrypt_key(connection))
    variants = [variant for value in values if value for variant in (value, base64.b64encode(value.encode()).decode())]
    matches = []
    for path in root.iterdir():
        if path.is_file() and path.suffix in {".py", ".json", ".jsonl", ".csv", ".md", ".txt", ".log", ".vue"}:
            text = path.read_text(errors="ignore")
            if any(value in text for value in variants):
                matches.append(path.name)
    result = {"database_access": "read_only", "secret_matches": matches, "passed": not matches}
    root.joinpath("redaction-verification.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
    assert result["passed"], "Configured secret found; no values exported"
