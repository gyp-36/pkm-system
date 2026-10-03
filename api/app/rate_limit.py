"""Small in-process guard for calls charged to a user's external model account."""

import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import HTTPException


_recent: dict[tuple[uuid.UUID, str], deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def check_limit(user_id: uuid.UUID, action: str, *, limit: int, window: float = 60.0) -> None:
    now = time.monotonic()
    with _lock:
        calls = _recent[(user_id, action)]
        while calls and now - calls[0] >= window:
            calls.popleft()
        if len(calls) >= limit:
            raise HTTPException(status_code=429, detail="模型请求过于频繁，请稍后再试")
        calls.append(now)
