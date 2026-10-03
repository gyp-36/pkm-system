"""Durable, retrying index worker for current note versions."""

import logging
import signal
import time

from app.indexer import claim_job, process_job, retry_job


logging.basicConfig(level=logging.INFO)
running = True


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
logging.info("index worker ready")
while running:
    try:
        job_id = claim_job()
        if job_id is None:
            time.sleep(2)
            continue
        try:
            process_job(job_id)
        except Exception as exc:
            logging.exception("index job failed: %s", job_id)
            retry_job(job_id, type(exc).__name__)
    except Exception:
        logging.exception("index worker database unavailable")
        time.sleep(5)
