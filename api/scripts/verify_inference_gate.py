"""Verify the shared inference gate serializes API/worker-style callers."""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from app.core.ollama_gate import ollama_inference_slot


lock = threading.Lock()
active = 0
maximum_active = 0
test_lock_key = int.from_bytes(uuid.uuid4().bytes[:8], "big", signed=True)


def run_call() -> None:
    global active, maximum_active
    with ollama_inference_slot("gate-verification", wait_timeout=10, lock_key=test_lock_key):
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.2)
        with lock:
            active -= 1


with ThreadPoolExecutor(max_workers=4) as executor:
    list(executor.map(lambda _: run_call(), range(4)))

if maximum_active != 1:
    raise SystemExit(f"expected max concurrency 1, got {maximum_active}")

try:
    with ollama_inference_slot("gate-exception-check", wait_timeout=2, lock_key=test_lock_key):
        raise RuntimeError("intentional release check")
except RuntimeError as exc:
    if str(exc) != "intentional release check":
        raise

with ollama_inference_slot("gate-after-exception", wait_timeout=2, lock_key=test_lock_key):
    pass

print("inference gate: max concurrency=1; lock released after exception")
