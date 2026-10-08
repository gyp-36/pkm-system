"""Single immutable-source acceptance run; retain every earlier attempt."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
manifest = json.loads((ROOT / "freeze-manifest.json").read_text())
api = Path("/tmp/assistant-remediation/api")
for path, digest in manifest["source_sha256"].items():
    if path.startswith("api/"):
        assert hashlib.sha256((api / path.removeprefix("api/")).read_bytes()).hexdigest() == digest, path
records = []
commands = [
    ["--output", "acceptance-results.jsonl"],
    ["--ids", (ROOT / "final-supplement-ids.txt").read_text().strip(), "--repeat-count", "2", "--output", "acceptance-supplement-results.jsonl"],
    ["--cases-file", "extra-cases.json", "--output", "acceptance-extra-results.jsonl"],
]
for args in commands:
    status = subprocess.call([sys.executable, str(ROOT / "launch_model.py"), *args])
    records.append({"arguments": args, "exit_code": status})
    (ROOT / "acceptance-status.json").write_text(json.dumps(records, indent=2))
    if status:
        raise SystemExit(status)
rows = [json.loads(line) for line in (ROOT / "acceptance-results.jsonl").read_text().splitlines() if line]
assert len(rows) == 280 and len({row["id"] for row in rows}) == 200
old = ROOT / "frozen-results.jsonl"
(ROOT / "pre-acceptance-results.jsonl").write_bytes(old.read_bytes())
old.write_bytes((ROOT / "acceptance-results.jsonl").read_bytes())
env = os.environ.copy()
env["DATABASE_URL"] = "postgresql+psycopg://security_test:SecurityTestOnly123@pkm-assistant-security-db:5432/assistant_security"
env["PYTHONPATH"] = str(api)
for script, output in [("http_validation.py", "http-results.json"), ("history_validation.py", "history-results.json")]:
    result = subprocess.run([sys.executable, str(ROOT / script)], env=env, cwd=api, capture_output=True, text=True, timeout=480)
    records.append({"script": script, "exit_code": result.returncode})
    if result.returncode:
        (ROOT / (script + ".acceptance-failure.txt")).write_text(result.stderr[-4000:])
    else:
        (ROOT / output).write_text(result.stdout.strip().splitlines()[-1] + "\n")
    (ROOT / "acceptance-status.json").write_text(json.dumps(records, indent=2))
print(json.dumps({"complete": True, "planned_executions": 414, "integration_exit_codes": [item["exit_code"] for item in records]}), flush=True)
