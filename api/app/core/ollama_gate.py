"""A PostgreSQL-backed, process-wide gate for local Ollama inference."""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Iterator

import httpx
from sqlalchemy import func, select

from app.core.db import engine


log = logging.getLogger(__name__)
_LOCK_KEY = 7_120_912_447_200_381_011
_MAX_WAIT_SECONDS = max(0.0, float(os.getenv("OLLAMA_INFERENCE_QUEUE_TIMEOUT_SECONDS", "300")))


class InferenceQueueTimeout(httpx.TimeoutException):
    """Raised when a caller cannot acquire the shared inference slot in time."""


@contextmanager
def ollama_inference_slot(
    operation: str, *, wait_timeout: float, lock_key: int = _LOCK_KEY,
) -> Iterator[int]:
    """Serialize model calls across API and worker processes using a session lock.

    Waiting callers release their database connection between short lock polls.
    The lock owner keeps one connection checked out until it explicitly unlocks;
    if the process dies, PostgreSQL releases the session lock automatically.
    """
    started = time.monotonic()
    deadline = started + min(max(0.0, wait_timeout), _MAX_WAIT_SECONDS)
    connection = None

    while connection is None:
        candidate = engine.connect()
        try:
            acquired = candidate.scalar(select(func.pg_try_advisory_lock(lock_key)))
            candidate.commit()
        except Exception:
            candidate.close()
            raise

        if acquired:
            connection = candidate
            break

        candidate.close()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            waited_ms = round((time.monotonic() - started) * 1000)
            log.warning("ollama_slot_timeout operation=%s wait_ms=%s", operation, waited_ms)
            raise InferenceQueueTimeout(f"Timed out waiting for Ollama inference slot ({operation})")
        time.sleep(min(0.25, remaining))

    waited_ms = round((time.monotonic() - started) * 1000)
    log.info("ollama_slot_acquired operation=%s wait_ms=%s", operation, waited_ms)
    try:
        yield waited_ms
    finally:
        try:
            unlocked = connection.scalar(select(func.pg_advisory_unlock(lock_key)))
            connection.commit()
            if not unlocked:
                log.error("ollama_slot_unlock_failed operation=%s", operation)
        finally:
            connection.close()
