"""Durable, retrying index worker for current note versions."""

import logging
import signal
import time

from app.core.request_context import correlation
from app.knowledge.indexer import claim_job, process_job, retry_job


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("index-worker")
running = True


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
log.info("worker_ready worker=index")
while running:
    try:
        job_id = claim_job()
        if job_id is None:
            time.sleep(2)
            continue
        try:
            # 以任务 ID 作为关联 ID，使本任务的日志行与审计行可互相印证。
            with correlation(job_id):
                process_job(job_id)
        except Exception as exc:
            log.exception("index_job_failed request_id=%s", job_id)
            retry_job(job_id, type(exc).__name__)
    except Exception:
        log.exception("index_worker_unavailable")
        time.sleep(5)
