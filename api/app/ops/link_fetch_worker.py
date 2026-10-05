"""Background agent for safely fetching user-submitted public web pages.

The API persists a draft first and this worker dispatches the bounded fetch
task. Network access remains inside the allowlisted HTTP fetcher; page content
is treated as untrusted text and is never executed as JavaScript.
"""

import logging
import signal
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.models import LinkDraft
from app.core.request_context import correlation
from app.knowledge.m3 import fetch_public_page


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("link-fetch-worker")
running = True
STALE_AFTER = timedelta(minutes=5)


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)


def _host(url: str) -> str:
    """只取域名用于日志：完整 URL 的查询串可能带敏感参数，不入日志。"""
    try:
        from urllib.parse import urlsplit

        return urlsplit(url).hostname or "-"
    except Exception:  # noqa: BLE001 - 日志辅助函数不得抛错
        return "-"


def claim_link_draft() -> tuple[str, str] | None:
    """Claim one pending draft and fail stale work without retrying its URL."""
    now = datetime.now(timezone.utc)
    stale_before = now - STALE_AFTER
    with SessionLocal() as db:
        stale = db.scalar(
            select(LinkDraft)
            .where(LinkDraft.status == "draft", LinkDraft.fetch_status == "processing", LinkDraft.updated_at < stale_before)
            .order_by(LinkDraft.updated_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if stale is not None:
            stale.fetch_status = "failed"
            stale.fetch_error = "抓取任务中断，按单次抓取策略不自动重试"
            stale.updated_at = now
            db.commit()
            return None
        row = db.scalar(
            select(LinkDraft)
            .where(
                LinkDraft.status == "draft",
                LinkDraft.fetch_status == "pending",
            )
            .order_by(LinkDraft.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return None
        row.fetch_status = "processing"
        row.fetch_error = None
        row.updated_at = now
        result = (str(row.id), row.source_url)
        db.commit()
        return result


def process_link_draft(draft_id: str, source_url: str) -> None:
    started_at = time.perf_counter()
    try:
        title, text = fetch_public_page(source_url)
        if not text.strip():
            raise ValueError("网页没有提取到可用正文，可手动粘贴正文")
        status, error = "ready", None
    except Exception as exc:
        from fastapi import HTTPException

        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        status, error, title, text = "failed", (detail or "网页抓取失败，可手动粘贴正文")[:500], None, None
        # 抓取失败要能定位到具体地址与原因，否则用户报「草稿一直失败」时无从查起。
        # 只记域名与错误摘要，不落完整 URL 查询串（可能含敏感参数）。
        log.warning(
            "link_draft_fetch_failed request_id=%s host=%s error=%s",
            draft_id, _host(source_url), error,
        )

    with SessionLocal() as db:
        row = db.scalar(
            select(LinkDraft)
            .where(LinkDraft.id == draft_id, LinkDraft.status == "draft")
            .with_for_update()
        )
        # A user may have pasted or edited content while a task was running.
        # PATCH changes the state away from processing, so never overwrite it.
        if row is None or row.fetch_status != "processing":
            db.rollback()
            return
        row.fetch_status = status
        row.fetch_error = error
        if status == "ready":
            row.title = (title or row.title or "网页草稿")[:240]
            row.snapshot_text = text or ""
            row.body_md = text or ""
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        log.info(
            "link_draft_fetch_finished request_id=%s status=%s elapsed_seconds=%.3f",
            draft_id, status, time.perf_counter() - started_at,
        )


log.info("worker_ready worker=link-fetch")
while running:
    try:
        task = claim_link_draft()
        if task is None:
            time.sleep(1.5)
            continue
        # 以草稿 ID 作为关联 ID：该草稿的抓取日志与后续审计可互相印证。
        with correlation(uuid.UUID(task[0])):
            process_link_draft(*task)
    except Exception:
        log.exception("link_fetch_worker_failed")
        time.sleep(3)
