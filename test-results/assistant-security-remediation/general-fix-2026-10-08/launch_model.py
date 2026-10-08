"""Launch in the original container without displaying provider configuration."""
import os
import subprocess
import sys

env = os.environ.copy()
env["SECURITY_PROVIDER_DATABASE_URL"] = env["DATABASE_URL"]
env["DATABASE_URL"] = "postgresql+psycopg://security_test:SecurityTestOnly123@pkm-assistant-security-db:5432/assistant_security"
env["PYTHONPATH"] = "/tmp/assistant-remediation/api"
raise SystemExit(subprocess.call([sys.executable, "/tmp/assistant-remediation/fix-tests/runner.py", *sys.argv[1:]], env=env, cwd="/tmp/assistant-remediation/api"))
