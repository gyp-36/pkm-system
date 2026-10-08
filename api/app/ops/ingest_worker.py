"""Retrying background file extraction worker."""

import logging
import os
import signal
import time
from datetime import datetime, time as datetime_time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.object_storage import ensure_bucket
from app.core.request_context import correlation
from app.knowledge.file_ingest import claim_job, process_job, retry_job
from app.knowledge.upload_sessions import cleanup_expired_sessions
from app.knowledge.archive import purge_expired_archive
from app.assistant.tracing import cleanup_expired_traces
from app.assistant.operations import cleanup_operations
from app.ops.maintenance import access_log_retention_days, purge_access_logs


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ingest-worker")
running = True
ARCHIVE_TIMEZONE = ZoneInfo("Asia/Shanghai")


def next_archive_midnight(now: datetime) -> datetime:
    tomorrow = now.date() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime_time.min, tzinfo=ARCHIVE_TIMEZONE)


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
extensions = {
    value.strip().lower()
    for value in os.getenv("INGEST_WORKER_EXTENSIONS", "").split(",")
    if value.strip()
}
run_maintenance = os.getenv("RUN_INGEST_MAINTENANCE", "true").lower() in {"1", "true", "yes"}
if run_maintenance:
    ensure_bucket()
log.info("worker_ready worker=ingest extensions=%s maintenance=%s", sorted(extensions) or "all", run_maintenance)
last_cleanup = 0.0
next_daily_maintenance = datetime.now(ARCHIVE_TIMEZONE).replace(
    hour=0, minute=0, second=0, microsecond=0
)
if run_maintenance:
    log.info("worker_maintenance_schedule at=00:00 timezone=Asia/Shanghai scope=archive_purge,access_log_purge")
while running:
    try:
        if run_maintenance and time.monotonic() - last_cleanup > 900:
            with SessionLocal() as db:
                cleanup_expired_sessions(db)
            cleanup_expired_traces()
            with SessionLocal.begin() as db:
                cleanup_operations(db)
            last_cleanup = time.monotonic()
        now = datetime.now(ARCHIVE_TIMEZONE)
        if run_maintenance and now >= next_daily_maintenance:
            try:
                purged = purge_expired_archive()
                log.info("archive_purge_done purged_notes=%s", purged)
            except Exception:
                log.exception("archive_purge_failed")
            try:
                # 访问日志有保留期，业务审计没有：前者是取证素材，后者是变更账本。
                keep_days = access_log_retention_days()
                removed = purge_access_logs(days=keep_days)
                log.info("access_log_purge_done retention_days=%s removed=%s", keep_days, removed)
            except Exception:
                log.exception("access_log_purge_failed")
            finally:
                next_daily_maintenance = next_archive_midnight(datetime.now(ARCHIVE_TIMEZONE))
                log.info("maintenance_next_run at=%s", next_daily_maintenance.isoformat())
        job_id = claim_job(extensions or None)
        if job_id is None:
            time.sleep(2)
            continue
        try:
            # 用任务 ID 作为关联 ID：该任务产生的日志行与审计行可共用一次查询串起来。
            with correlation(job_id, actor_id=None):
                process_job(job_id)
        except Exception as exc:
            log.exception("ingest_job_failed request_id=%s", job_id)
            retry_job(job_id, type(exc).__name__)
    except Exception:
        log.exception("ingest_worker_unavailable")
        time.sleep(5)
