"""Read-only original-config secret check and original/validation runtime fingerprints."""
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app")
from sqlalchemy import select
from app.core.db import SessionLocal, engine
from app.core.models import ModelConnection
from app.assistant.model_connection import decrypt_key

root = Path(__file__).resolve().parent
with SessionLocal() as db:
    db.connection().exec_driver_sql("SET TRANSACTION READ ONLY")
    row = db.scalar(select(ModelConnection).where(ModelConnection.deleted_at.is_(None)))
    secrets = {"configured_model_key": decrypt_key(row), "original_database_dsn": engine.url.render_as_string(hide_password=False)}
    for key in ["PKM_CREDENTIAL_KEY", "PKM_SESSION_SECRET"]:
        if os.environ.get(key):
            secrets[key] = os.environ[key]
    observed = {key: [] for key in secrets}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".jsonl", ".py", ".mjs", ".md", ".csv", ".html", ".txt", ".log"}:
            content = path.read_text(errors="ignore")
            for label, value in secrets.items():
                if value and (value in content or base64.b64encode(value.encode()).decode() in content):
                    observed[label].append(str(path.relative_to(root)))
paths = ["app/assistant/assistant.py", "app/assistant/conversations.py", "app/assistant/tracing.py", "app/assistant/policy.py", "app/assistant/operations.py", "app/assistant/response_guard.py", "app/prompts/answer_system.txt"]
fingerprints = {}
for label, base in [("original_service", Path("/app")), ("validation_service", Path("/tmp/assistant-remediation/api"))]:
    fingerprints[label] = {path: hashlib.sha256((base / path).read_bytes()).hexdigest() if (base / path).exists() else None for path in paths}
result = {"database_access": "read_only", "secret_presence": observed, "passed_secret_presence_check": not any(observed.values()), "runtime_fingerprints": fingerprints,
          "personal_service_deployed": False, "original_service_is_acceptance_version": fingerprints["original_service"] == fingerprints["validation_service"]}
(root / "artifact-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False))
assert result["passed_secret_presence_check"], "Configured secret found; no values displayed"
