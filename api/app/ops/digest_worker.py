"""Poll account schedules and produce one report note per claimed period."""

import logging
import signal
import time

from app.assistant.digests import claim_run, enqueue_due, process_run
from app.core.request_context import correlation


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("digest-worker")
running = True


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
log.info("worker_ready worker=digest")

while running:
    try:
        enqueue_due()
        run_id = claim_run()
        if run_id is not None:
            try:
                # 摘要运行会产出笔记，其审计行需要能反查到这次运行。
                with correlation(run_id):
                    process_run(run_id)
            except Exception:
                log.exception("digest_run_failed request_id=%s", run_id)
        else:
            time.sleep(10)
    except Exception:
        log.exception("digest_worker_unavailable")
        time.sleep(5)
