"""Scheduled, evidence-backed summaries saved as editable Markdown notes."""

import difflib
import json
import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from langchain.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.assistant.model_connection import chat_model, decrypt_key, require_connection
from app.auth.auth import Db, UserId
from app.core.db import SessionLocal
from app.core.enums import AuditAction, AuditActor, AuditEntityType
from app.core.lifecycle import record_event, record_revision
from app.core.models import AuditEvent, DigestRun, DigestSettings, Note, NoteFileVersion, NoteReminder, NoteRevision
from app.knowledge.notes import queue_index
from app.prompts import load_prompt
from app.contracts.digests import DigestListOut, DigestRunOut, DigestSettingsOut


log = logging.getLogger(__name__)


router = APIRouter(prefix="/v1/digests", tags=["digests"])
LOCAL_ZONE = ZoneInfo("Asia/Shanghai")
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
SOURCE_PATTERN = re.compile(r"\[S(\d+)\]")
# [S编号] 是模型与服务端之间的内部证据键，只用于校验与回溯来源，绝不允许留在最终正文里。
# 区间写法（[S3]-[S19]）无法还原成完整来源，裸编号（见 S5）则说明模型把内部键当正文写了，两种都判为不合规输出。
SOURCE_RANGE_PATTERN = re.compile(r"\[S\d+\]\s*[-–—~～至到]\s*\[S\d+\]")
BARE_SOURCE_PATTERN = re.compile(r"(?<!\[)S\d{1,2}(?!\])")
CITATION_LABEL_MAX = 30
MAX_ACTIVITIES = 40


class SettingsUpdate(BaseModel):
    daily_enabled: bool = False
    daily_time: str = "21:00"
    weekly_enabled: bool = False
    weekly_weekday: int = Field(default=6, ge=0, le=6)
    weekly_time: str = "21:00"

    @field_validator("daily_time", "weekly_time")
    @classmethod
    def valid_time(cls, value: str) -> str:
        if not TIME_PATTERN.fullmatch(value):
            raise ValueError("时间应为 HH:MM")
        return value


class SettingsPatch(BaseModel):
    daily_enabled: bool | None = None
    daily_time: str | None = None
    weekly_enabled: bool | None = None
    weekly_weekday: int | None = Field(default=None, ge=0, le=6)
    weekly_time: str | None = None

    @field_validator("daily_time", "weekly_time")
    @classmethod
    def valid_time(cls, value: str | None) -> str | None:
        if value is not None and not TIME_PATTERN.fullmatch(value):
            raise ValueError("时间应为 HH:MM")
        return value


def settings_json(row: DigestSettings | None) -> dict:
    return {
        "daily_enabled": bool(row.daily_enabled) if row else False,
        "daily_time": row.daily_time or "21:00" if row else "21:00",
        "weekly_enabled": bool(row.weekly_enabled) if row else False,
        "weekly_weekday": row.weekly_weekday if row and row.weekly_weekday is not None else 6,
        "weekly_time": row.weekly_time or "21:00" if row else "21:00",
        "timezone": "Asia/Shanghai",
        "daily_next_at": row.daily_next_at.isoformat() if row and row.daily_next_at else None,
        "weekly_next_at": row.weekly_next_at.isoformat() if row and row.weekly_next_at else None,
    }


def next_occurrence(kind: str, *, after: datetime, at_time: str, weekday: int = 6) -> datetime:
    local_now = after.astimezone(LOCAL_ZONE)
    hour, minute = map(int, at_time.split(":"))
    day = local_now.date()
    if kind == "weekly":
        day += timedelta(days=(weekday - day.weekday()) % 7)
    candidate = datetime.combine(day, time(hour, minute), tzinfo=LOCAL_ZONE)
    if candidate <= local_now:
        candidate += timedelta(days=7 if kind == "weekly" else 1)
    return candidate.astimezone(timezone.utc)


def run_json(row: DigestRun) -> dict:
    return {
        "id": str(row.id), "kind": row.kind, "status": row.status,
        "note_id": str(row.note_id) if row.note_id else None,
        "period_start": row.period_start.isoformat(), "period_end": row.period_end.isoformat(),
        "scheduled_at": row.scheduled_at.isoformat(), "error": row.error,
    }


@router.get("/settings", response_model=DigestSettingsOut)
def get_settings(db: Db, user_id: UserId) -> dict:
    return settings_json(db.get(DigestSettings, user_id))


@router.put("/settings", response_model=DigestSettingsOut)
def put_settings(body: SettingsUpdate, db: Db, user_id: UserId) -> dict:
    return _save_settings(db, user_id, body.model_dump())


@router.patch("/settings", response_model=DigestSettingsOut)
def patch_settings(body: SettingsPatch, db: Db, user_id: UserId) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="请提供有效的报告设置")
    return _save_settings(db, user_id, changes)


def _save_settings(db: Db, user_id: uuid.UUID, changes: dict) -> dict:
    now = datetime.now(timezone.utc)
    row = db.scalar(select(DigestSettings).where(DigestSettings.user_id == user_id).with_for_update())
    if row is None:
        row = DigestSettings(user_id=user_id)
        db.add(row)
    current = settings_json(row)
    body = SettingsUpdate(**{key: changes.get(key, current[key]) for key in
                             ("daily_enabled", "daily_time", "weekly_enabled", "weekly_weekday", "weekly_time")})
    if row.daily_enabled != body.daily_enabled or row.daily_time != body.daily_time or (body.daily_enabled and row.daily_next_at is None):
        row.daily_next_at = next_occurrence("daily", after=now, at_time=body.daily_time) if body.daily_enabled else None
    if (row.weekly_enabled != body.weekly_enabled or row.weekly_time != body.weekly_time
            or row.weekly_weekday != body.weekly_weekday or (body.weekly_enabled and row.weekly_next_at is None)):
        row.weekly_next_at = next_occurrence("weekly", after=now, at_time=body.weekly_time, weekday=body.weekly_weekday) if body.weekly_enabled else None
    row.daily_enabled, row.daily_time = body.daily_enabled, body.daily_time
    row.weekly_enabled, row.weekly_time, row.weekly_weekday = body.weekly_enabled, body.weekly_time, body.weekly_weekday
    row.updated_at = now
    record_event(db, user_id, AuditAction.UPDATE, AuditEntityType.DIGEST, user_id,
                 details={"changed": sorted(changes)})
    db.commit()
    return settings_json(row)


@router.get("", response_model=DigestListOut)
def list_runs(
    db: Db, user_id: UserId, kind: str | None = Query(default=None, pattern="^(daily|weekly)$"),
    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
) -> dict:
    query = select(DigestRun).where(DigestRun.user_id == user_id)
    if kind is not None:
        query = query.where(DigestRun.kind == kind)
    rows = db.scalars(query.order_by(DigestRun.scheduled_at.desc(), DigestRun.id.desc()).offset(offset).limit(limit + 1)).all()
    page = rows[:limit]
    note_ids = [row.note_id for row in page if row.note_id is not None]
    report_notes = {note_id: deleted_at for note_id, deleted_at in db.execute(select(Note.id, Note.deleted_at).where(
        Note.id.in_(note_ids), Note.user_id == user_id,
    )).all()} if note_ids else {}
    return {
        "items": [{
            **run_json(row),
            "note_active": row.note_id in report_notes and report_notes[row.note_id] is None,
            "note_archived": row.note_id in report_notes and report_notes[row.note_id] is not None,
        } for row in page],
        "next_offset": offset + limit if len(rows) > limit else None,
    }


@router.post("/{run_id}/retry", response_model=DigestRunOut)
def retry_run(run_id: uuid.UUID, db: Db, user_id: UserId) -> dict:
    row = db.scalar(select(DigestRun).where(DigestRun.id == run_id, DigestRun.user_id == user_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="报告任务不存在")
    if row.status != "failed" or row.note_id is not None:
        raise HTTPException(status_code=409, detail="报告任务当前不可重试")
    require_connection(db, user_id)
    row.status, row.error = "pending", None
    row.updated_at = datetime.now(timezone.utc)
    record_event(db, user_id, AuditAction.UPDATE, AuditEntityType.DIGEST, row.id,
                 details={"changed": ["status"], "status": "pending", "retry": True})
    db.commit()
    return run_json(row)


def enqueue_due(now: datetime | None = None) -> int:
    """Create due runs in bounded batches; a restart preserves every missed slot."""
    now = now or datetime.now(timezone.utc)
    created = 0
    with SessionLocal() as db:
        rows = db.scalars(select(DigestSettings).where(or_(
            and_(DigestSettings.daily_enabled.is_(True), DigestSettings.daily_next_at <= now),
            and_(DigestSettings.weekly_enabled.is_(True), DigestSettings.weekly_next_at <= now),
        )).with_for_update(skip_locked=True)).all()
        for settings in rows:
            for kind in ("daily", "weekly"):
                enabled = getattr(settings, f"{kind}_enabled")
                next_at = getattr(settings, f"{kind}_next_at")
                if not enabled or next_at is None or next_at > now:
                    continue
                at_time = getattr(settings, f"{kind}_time")
                weekday = settings.weekly_weekday
                processed = 0
                while next_at <= now and processed < 30:
                    local = next_at.astimezone(LOCAL_ZONE)
                    slot_key = local.date().isoformat() if kind == "daily" else f"{local.isocalendar().year}-W{local.isocalendar().week:02d}"
                    exists = db.scalar(select(DigestRun.id).where(
                        DigestRun.user_id == settings.user_id, DigestRun.kind == kind, DigestRun.slot_key == slot_key,
                    ))
                    if exists is None:
                        start = next_at - timedelta(days=1 if kind == "daily" else 7)
                        db.add(DigestRun(user_id=settings.user_id, kind=kind, slot_key=slot_key,
                                         scheduled_at=next_at, period_start=start, period_end=next_at))
                        created += 1
                    next_at = next_occurrence(kind, after=next_at, at_time=at_time, weekday=weekday)
                    processed += 1
                setattr(settings, f"{kind}_next_at", next_at)
        db.commit()
    return created


def claim_run() -> uuid.UUID | None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        stale = db.scalars(select(DigestRun).where(
            DigestRun.status == "processing", DigestRun.updated_at < now - timedelta(minutes=10),
        ).with_for_update(skip_locked=True)).all()
        for row in stale:
            row.status, row.error, row.updated_at = "failed", "生成任务中断，请重试", now
        row = db.scalar(select(DigestRun).where(DigestRun.status == "pending").order_by(DigestRun.scheduled_at, DigestRun.id).with_for_update(skip_locked=True).limit(1))
        if row is not None:
            row.status, row.updated_at = "processing", now
            row.attempts += 1
        db.commit()
        return row.id if row else None


def _section(run: DigestRun, happened: datetime) -> str:
    if run.kind == "daily" and happened.astimezone(LOCAL_ZONE).date() < run.scheduled_at.astimezone(LOCAL_ZONE).date():
        return "前一日晚间补记"
    return "本期"


def collect_evidence(db: Session, run: DigestRun) -> tuple[list[dict], list[dict], int]:
    """Use persisted user activity and snapshots; never treat generated reports as input."""
    generated_ids = set(db.scalars(select(DigestRun.note_id).where(DigestRun.user_id == run.user_id, DigestRun.note_id.is_not(None))).all())
    events = db.scalars(select(AuditEvent).where(
        AuditEvent.user_id == run.user_id, AuditEvent.entity_type == AuditEntityType.NOTE,
        AuditEvent.action.in_([AuditAction.CREATE, AuditAction.UPDATE, AuditAction.RESTORE]),
        AuditEvent.created_at >= run.period_start, AuditEvent.created_at < run.period_end,
    ).order_by(AuditEvent.created_at).limit(2000)).all()
    files = db.scalars(select(NoteFileVersion).where(
        NoteFileVersion.user_id == run.user_id, NoteFileVersion.created_at >= run.period_start,
        NoteFileVersion.created_at < run.period_end,
    ).order_by(NoteFileVersion.created_at).limit(500)).all()
    reminders = db.scalars(select(NoteReminder).where(
        NoteReminder.user_id == run.user_id, NoteReminder.note_id.is_not(None),
        or_(and_(NoteReminder.created_at >= run.period_start, NoteReminder.created_at < run.period_end),
            and_(NoteReminder.completed_at >= run.period_start, NoteReminder.completed_at < run.period_end),
            and_(NoteReminder.updated_at >= run.period_start, NoteReminder.updated_at < run.period_end)),
    ).limit(500)).all()
    groups: dict[tuple[uuid.UUID, str], dict] = defaultdict(lambda: {"times": [], "actions": set(), "versions": [], "files": [], "reminders": []})
    for event in events:
        if event.entity_id in generated_ids:
            continue
        group = groups[(event.entity_id, _section(run, event.created_at))]
        group["times"].append(event.created_at)
        group["actions"].add(AuditAction(event.action).name.lower())
        if event.entity_version is not None:
            group["versions"].append(event.entity_version)
        if "taxonomy" in (event.details or {}).get("fields", []):
            group["actions"].add("classification_changed")
    for file in files:
        if file.note_id in generated_ids:
            continue
        group = groups[(file.note_id, _section(run, file.created_at))]
        group["times"].append(file.created_at)
        group["actions"].add("file_saved")
        group["files"].append(file.filename)
    for reminder in reminders:
        if reminder.note_id in generated_ids:
            continue
        if reminder.completed_at and run.period_start <= reminder.completed_at < run.period_end:
            when, action = reminder.completed_at, "reminder_completed"
        elif run.period_start <= reminder.created_at < run.period_end:
            when, action = reminder.created_at, "reminder_created"
        else:
            when = reminder.updated_at
            action = "reminder_cancelled" if reminder.status == "cancelled" else "reminder_updated"
        group = groups[(reminder.note_id, _section(run, when))]
        group["times"].append(when)
        group["actions"].add(action)
        group["reminders"].append(reminder.text)
    activities: list[dict] = []
    references: list[dict] = []
    for (note_id, section), group in sorted(groups.items(), key=lambda item: min(item[1]["times"]), reverse=True):
        note = db.scalar(select(Note).where(Note.id == note_id, Note.user_id == run.user_id, Note.deleted_at.is_(None)))
        if note is None:
            continue
        versions = group["versions"]
        after = db.scalar(select(NoteRevision).where(
            NoteRevision.user_id == run.user_id, NoteRevision.note_id == note_id,
            NoteRevision.version <= max(versions),
        ).order_by(NoteRevision.version.desc()).limit(1)) if versions else None
        before = db.scalar(select(NoteRevision).where(
            NoteRevision.user_id == run.user_id, NoteRevision.note_id == note_id,
            NoteRevision.version < min(versions),
        ).order_by(NoteRevision.version.desc()).limit(1)) if versions else None
        first = db.scalar(select(NoteRevision).where(
            NoteRevision.user_id == run.user_id, NoteRevision.note_id == note_id,
            NoteRevision.version == min(versions),
        )) if versions and before is None else before
        after_body = (after.body_md if after else note.body_md) or ""
        before_body = before.body_md if before else ""
        if (group["actions"] == {"update"} and before is not None and after is not None
                and before.title == after.title and before.body_md == after.body_md
                and before.notebook_id == after.notebook_id and set(before.tag_ids) == set(after.tag_ids)):
            continue
        classification_change = {
            "notebook": bool(first and after and first.notebook_id != after.notebook_id),
            "tags": bool(first and after and set(first.tag_ids) != set(after.tag_ids)),
        }
        if any(classification_change.values()):
            group["actions"].add("classification_changed")
        if first and after and first.title != after.title:
            group["actions"].add("title_changed")
        diff = "\n".join(difflib.unified_diff(before_body.splitlines(), after_body.splitlines(), lineterm=""))[:1600]
        citation = f"S{len(activities) + 1}"
        activities.append({
            "citation": citation, "section": section, "occurred_at": min(group["times"]).isoformat(),
            "actions": sorted(group["actions"]), "note_title": (after.title if after else note.title),
            "previous_title": first.title if first and after and first.title != after.title else None,
            "classification_change": classification_change,
            "published_from_web": bool(note.source_url),
            "note_version": after.version if after else note.version,
            "content_change": diff, "current_excerpt": after_body[:700],
            "files": sorted(set(group["files"])), "reminders": sorted(set(group["reminders"])),
        })
        references.append({"citation": citation, "note_id": str(note.id), "note_version": after.version if after else note.version,
                           "title": after.title if after else note.title})
        if len(activities) == MAX_ACTIVITIES:
            break
    return activities, references, max(0, len(groups) - len(activities))


def _report_title(run: DigestRun) -> str:
    local_end = run.period_end.astimezone(LOCAL_ZONE)
    if run.kind == "daily":
        return f"日报｜{local_end:%Y-%m-%d}"
    local_start = run.period_start.astimezone(LOCAL_ZONE)
    return f"周报｜{local_start:%Y-%m-%d}—{local_end:%Y-%m-%d}"


def _generate_body(run: DigestRun, activities: list[dict], omitted: int, model) -> str:
    if not activities:
        return f"# {_report_title(run)}\n\n## 本期记录\n本期没有可用于生成回顾的已保存笔记活动。"
    payload = {
        "report_type": run.kind, "period_start": run.period_start.astimezone(LOCAL_ZONE).isoformat(),
        "period_end": run.period_end.astimezone(LOCAL_ZONE).isoformat(),
        "daily_current_date": run.period_end.astimezone(LOCAL_ZONE).date().isoformat() if run.kind == "daily" else None,
        "activities": activities, "omitted_activity_groups": omitted,
    }
    response = model.invoke([
        SystemMessage(content=load_prompt("note_digest_system.txt")),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
    ])
    body = response.content if isinstance(response.content, str) else ""
    body = body.strip()
    if not body or len(body) > 100_000:
        raise ValueError("模型没有返回有效报告")
    return body


def _citation_label(title: str) -> str:
    """来源链接的可见文本是笔记标题：用户只需知道来源是哪篇文章。"""
    label = " ".join((title or "").split()) or "无标题笔记"
    if len(label) > CITATION_LABEL_MAX:
        label = label[:CITATION_LABEL_MAX].rstrip() + "…"
    return label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _verified_body(body: str, refs: list[dict]) -> str:
    """校验并替换内部来源键。[S编号] 只参与校验和定位，正文里只留下来源笔记标题的链接。"""
    lookup = {ref["citation"]: ref for ref in refs}
    found = SOURCE_PATTERN.findall(body)
    if refs and not found:
        raise ValueError("报告缺少来源引用")
    if SOURCE_RANGE_PATTERN.search(body) or BARE_SOURCE_PATTERN.search(body):
        raise ValueError("报告来源引用只能逐个标注 [S编号]，不能写成区间或裸编号")
    if any(f"S{number}" not in lookup for number in found):
        raise ValueError("报告包含无效来源引用")
    for line in body.splitlines():
        if line.lstrip().startswith(("- ", "* ")) and "暂无可核对记录" not in line and not SOURCE_PATTERN.search(line):
            raise ValueError("报告存在无来源的具体结论")
    body = re.sub(r"\]\s*(?=\[S\d+\])", "]、", body)

    def render(match: re.Match) -> str:
        ref = lookup["S" + match.group(1)]
        return f"[{_citation_label(ref['title'])}](#/notes?note={ref['note_id']})"

    rendered = SOURCE_PATTERN.sub(render, body)
    if SOURCE_PATTERN.search(rendered):
        raise ValueError("报告仍包含未替换的内部来源编号")
    return rendered


def process_run(run_id: uuid.UUID) -> None:
    # 本模块从 datetime 导入了 time（时间类型），不能用 time.monotonic 计时。
    started_at = datetime.now(timezone.utc)
    try:
        with SessionLocal() as db:
            run = db.scalar(select(DigestRun).where(DigestRun.id == run_id, DigestRun.status == "processing"))
            if run is None:
                log.info("digest_run_skipped request_id=%s reason=not_claimed", run_id)
                return
            attempt = run.attempts
            activities, refs, omitted = collect_evidence(db, run)
            # 证据条数决定了报告可信度，是排查「报告为什么是空的」的第一手依据。
            log.info(
                "digest_evidence_collected request_id=%s user=%s kind=%s activities=%s sources=%s omitted=%s",
                run_id, run.user_id, run.kind, len(activities), len(refs), omitted,
            )
            connection = require_connection(db, run.user_id)
            key = decrypt_key(connection)
            model_name = connection.model_name
            title = _report_title(run)
            body = _generate_body(run, activities, omitted, chat_model(key, model_name, max_tokens=1800))
            body = _verified_body(body, refs)
        with SessionLocal() as db:
            run = db.scalar(select(DigestRun).where(DigestRun.id == run_id).with_for_update())
            if run is None or run.status != "processing" or run.note_id is not None or run.attempts != attempt:
                return
            for ref in refs:
                source_id = uuid.UUID(ref["note_id"])
                source = db.scalar(select(Note).where(
                    Note.id == source_id, Note.user_id == run.user_id, Note.deleted_at.is_(None),
                ))
                revision = db.scalar(select(NoteRevision.id).where(
                    NoteRevision.note_id == source_id, NoteRevision.user_id == run.user_id,
                    NoteRevision.version == ref["note_version"],
                ))
                if source is None or revision is None:
                    raise ValueError("报告来源笔记或引用版本已失效")
            note = Note(user_id=run.user_id, title=title, body_md=body, version=1)
            db.add(note)
            db.flush()
            queue_index(db, note)
            record_revision(db, note, [])
            record_event(db, run.user_id, AuditAction.CREATE, AuditEntityType.NOTE, note.id,
                         entity_version=1, actor_type=AuditActor.SYSTEM)
            run.note_id, run.status, run.error = note.id, "ready", None
            run.source_refs = refs
            run.updated_at = datetime.now(timezone.utc)
            produced_note_id, body_chars = note.id, len(body)
            db.commit()
        log.info(
            "digest_run_finished request_id=%s note=%s sources=%s body_chars=%s elapsed_seconds=%.3f",
            run_id, produced_note_id, len(refs), body_chars,
            (datetime.now(timezone.utc) - started_at).total_seconds(),
        )
    except Exception as exc:
        with SessionLocal() as db:
            run = db.scalar(select(DigestRun).where(DigestRun.id == run_id).with_for_update())
            if run is not None and run.status == "processing" and run.note_id is None:
                run.status = "failed"
                run.error = (str(exc.detail) if isinstance(exc, HTTPException) else str(exc))[:500]
                run.updated_at = datetime.now(timezone.utc)
                db.commit()
                log.error(
                    "digest_run_failed request_id=%s user=%s error=%s",
                    run_id, run.user_id, run.error,
                )
        raise
