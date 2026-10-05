"""运维排障查询出口：按请求 / 实体 / 用户维度追溯一次操作。

`pkm_audit_events` 与 `pkm_access_logs` 里的枚举都是 `smallint`，直接连库看
数字很难读，本脚本负责还原成语义字符串并做脱敏。它是**纯读取**的运维工具，
不提供任何 HTTP 接口，也不进入前端——产品决策是用户侧不展示操作历史。

典型用法：

    # 一次请求的全链路：业务审计 + 访问日志
    python -m scripts.query_audit --request-id 6f1c... --access

    # 这半年里谁动过这篇笔记
    python -m scripts.query_audit --entity-id 3ab2... --since 180d

    # 某账号最近的失败动作
    python -m scripts.query_audit --user-id 9d4e... --failed --since 7d

    # 只统计条数，不打印明细
    python -m scripts.query_audit --user-id 9d4e... --count
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.core.enums import AuditAction, AuditActor, AuditEntityType, AuditOutcome
from app.core.models import AccessLog, AuditEvent


DEFAULT_LIMIT = 50
MAX_LIMIT = 2000

# 脱敏标记：`details` 中出现这些子串的键，其值一律不打印。
# 覆盖 api_key / credential_ciphertext / password / token / secret 等命名习惯。
SENSITIVE_MARKERS = ("key", "password", "token", "secret", "cipher", "credential")
REDACTED = "***"


def _redact(value: Any) -> Any:
    """递归脱敏：按**键名**判断，不扫描值的字面量（易误伤正文）。"""
    if isinstance(value, dict):
        return {
            key: (REDACTED if any(marker in str(key).lower() for marker in SENSITIVE_MARKERS) else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _parse_time(raw: str) -> datetime:
    """接受 ISO 8601 或相对量（`24h` / `7d` / `90m`）。"""
    text = raw.strip()
    suffix = text[-1:].lower()
    if suffix in {"h", "d", "m"} and text[:-1].isdigit():
        amount = int(text[:-1])
        unit = {"h": "hours", "d": "days", "m": "minutes"}[suffix]
        return datetime.now(timezone.utc) - timedelta(**{unit: amount})
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _resolve_enum(raw: str, enum_cls, label: str) -> int:
    """同时接受枚举名（CREATE / note）与裸数字（4）。"""
    token = raw.strip()
    if token.isdigit():
        return int(token)
    upper = token.upper()
    if upper in enum_cls.__members__:
        return int(enum_cls[upper])
    options = ", ".join(member.name for member in enum_cls)
    raise SystemExit(f"{label} 取值无效：{raw}\n可选：{options}（或使用数字）")


def _name(enum_cls, value: Any) -> str:
    if value is None:
        return "-"
    try:
        return enum_cls(int(value)).name
    except ValueError:
        return f"?{value}"


def _iso(moment: datetime | None) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if moment else "-"


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _event_view(row: AuditEvent) -> dict:
    return {
        "created_at": _iso(row.created_at),
        "action": _name(AuditAction, row.action),
        "entity_type": _name(AuditEntityType, row.entity_type),
        "entity_id": str(row.entity_id),
        "entity_version": row.entity_version,
        "actor": _name(AuditActor, row.actor_type),
        "actor_id": str(row.actor_id) if row.actor_id else None,
        "user_id": str(row.user_id),
        "outcome": _name(AuditOutcome, row.outcome) if row.outcome is not None else "SUCCESS",
        "request_id": str(row.request_id) if row.request_id else None,
        "details": _redact(row.details or {}),
    }


def _access_view(row: AccessLog) -> dict:
    return {
        "created_at": _iso(row.created_at),
        "method": row.method,
        "path": row.path,
        "status_code": row.status_code,
        "duration_ms": row.duration_ms,
        "user_id": str(row.user_id) if row.user_id else None,
        "ip": row.ip,
        "user_agent": row.user_agent,
        "request_id": str(row.request_id),
    }


def _build_filters(args: argparse.Namespace) -> list:
    filters = []
    if args.user_id:
        filters.append(AuditEvent.user_id == args.user_id)
    if args.entity_id:
        filters.append(AuditEvent.entity_id == args.entity_id)
    if args.request_id:
        filters.append(AuditEvent.request_id == args.request_id)
    if args.action is not None:
        filters.append(AuditEvent.action == args.action)
    if args.entity_type is not None:
        filters.append(AuditEvent.entity_type == args.entity_type)
    if args.failed:
        filters.append(AuditEvent.outcome == int(AuditOutcome.FAILED))
    if args.since:
        filters.append(AuditEvent.created_at >= args.since)
    if args.until:
        filters.append(AuditEvent.created_at <= args.until)
    return filters


def _print_events(rows: Iterable[AuditEvent]) -> None:
    rows = list(rows)
    if not rows:
        print("（无匹配的业务审计）")
        return
    print(f"业务审计 {len(rows)} 条：")
    for row in rows:
        view = _event_view(row)
        marker = "✗" if view["outcome"] == "FAILED" else "✓"
        print(
            f"  {marker} {view['created_at']}  {view['action']:<8} {view['entity_type']:<14} "
            f"{view['entity_id'][:8]}…  v={view['entity_version'] or '-'}  {view['outcome']}"
        )
        print(f"      user={view['user_id']}  actor={view['actor']}/{view['actor_id'] or '-'}")
        print(f"      request_id={view['request_id'] or '-'}")
        if view["details"]:
            print(f"      details={json.dumps(view['details'], ensure_ascii=False)}")


def _print_access(rows: Iterable[AccessLog]) -> None:
    rows = list(rows)
    if not rows:
        print("（无匹配的访问日志）")
        return
    print(f"访问日志 {len(rows)} 条：")
    for row in rows:
        view = _access_view(row)
        print(f"  {view['created_at']}  {view['method']:<7} {view['status_code']}  {_truncate(view['path'], 60)}")
        print(f"      {view['duration_ms']}ms  user={view['user_id'] or '匿名'}  ip={view['ip'] or '-'}")
        print(f"      request_id={view['request_id']}  ua={_truncate(view['user_agent'] or '-', 70)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="按请求 / 实体 / 用户追溯审计与访问日志（只读）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--user-id", type=uuid.UUID, help="账号 ID")
    parser.add_argument("--entity-id", type=uuid.UUID, help="动作对象 ID（笔记、笔记本、模板……）")
    parser.add_argument("--request-id", type=uuid.UUID, help="请求 ID（响应头 X-Request-Id）")
    parser.add_argument("--action", help="动作，如 CREATE / delete / 7")
    parser.add_argument("--entity-type", help="实体类型，如 NOTE / reminder / 3")
    parser.add_argument("--failed", action="store_true", help="只看失败的动作")
    parser.add_argument("--since", help="起始时间，ISO 8601 或相对量（7d / 24h / 30m）")
    parser.add_argument("--until", help="结束时间，ISO 8601 或相对量")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"最多返回条数（默认 {DEFAULT_LIMIT}）")
    parser.add_argument("--access", dest="access", action="store_true", default=None,
                        help="同时输出访问日志（给定 --request-id 时默认开启）")
    parser.add_argument("--no-access", dest="access", action="store_false",
                        help="即使给了 --request-id 也不输出访问日志")
    parser.add_argument("--count", action="store_true", help="只输出条数统计")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出，便于管道处理")
    args = parser.parse_args()

    if not any([args.user_id, args.entity_id, args.request_id, args.failed]):
        parser.error("至少需要指定 --user-id / --entity-id / --request-id / --failed 之一，避免全表扫描")

    args.limit = max(1, min(args.limit, MAX_LIMIT))
    args.since = _parse_time(args.since) if args.since else None
    args.until = _parse_time(args.until) if args.until else None
    args.action = _resolve_enum(args.action, AuditAction, "动作") if args.action else None
    args.entity_type = _resolve_enum(args.entity_type, AuditEntityType, "实体类型") if args.entity_type else None
    with_access = args.access if args.access is not None else bool(args.request_id)

    with SessionLocal() as db:
        events = list(db.scalars(
            select(AuditEvent)
            .where(*_build_filters(args))
            .order_by(AuditEvent.created_at.desc())
            .limit(args.limit)
        ).all())

        access_rows: list[AccessLog] = []
        if with_access:
            access_filters = []
            if args.request_id:
                access_filters.append(AccessLog.request_id == args.request_id)
            if args.user_id:
                access_filters.append(AccessLog.user_id == args.user_id)
            if args.since:
                access_filters.append(AccessLog.created_at >= args.since)
            if args.until:
                access_filters.append(AccessLog.created_at <= args.until)
            if access_filters:
                access_rows = list(db.scalars(
                    select(AccessLog)
                    .where(*access_filters)
                    .order_by(AccessLog.created_at.desc())
                    .limit(args.limit)
                ).all())

        matched_total = db.scalar(
            select(func.count()).select_from(AuditEvent).where(*_build_filters(args))
        ) if args.count else None

    if args.json:
        print(json.dumps({
            "audit_events": [_event_view(row) for row in events],
            "access_logs": [_access_view(row) for row in access_rows],
        }, ensure_ascii=False, indent=2))
        return 0

    if args.count:
        print(f"匹配的业务审计：{matched_total} 条（--limit 仅限制明细输出）")
        return 0

    _print_events(events)
    if with_access:
        print()
        _print_access(access_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
