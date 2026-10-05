"""按保留期清理过期的请求访问日志（CLI 入口）。

真正的清理逻辑在 `app.ops.maintenance.purge_access_logs`，这样 worker 的
每日维护循环可以直接复用，无需反向依赖 `scripts` 包。

**只清理访问日志，不清理业务审计**（`pkm_audit_events`）：两者的价值不同——
访问日志是「取证素材」，密度高、价值随时间快速衰减，90 天足够覆盖排障窗口；
业务审计是「变更账本」，行数增长慢、事后追责时需要长期可得，因此不设自动过期，
只在账号注销时随个人数据一并清除。

保留期由 `ACCESS_LOG_RETENTION_DAYS` 控制，默认 90 天。

    python -m scripts.purge_access_logs --dry-run     # 先看会删多少
    python -m scripts.purge_access_logs --days 30     # 临时覆盖保留期
"""

from __future__ import annotations

import argparse
import sys

from app.ops.maintenance import (
    ACCESS_LOG_BATCH_SIZE,
    ACCESS_LOG_DEFAULT_RETENTION_DAYS,
    ACCESS_LOG_RETENTION_ENV,
    access_log_retention_days,
    purge_access_logs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="清理过期的请求访问日志（不触碰业务审计）")
    parser.add_argument("--days", type=int, help=f"保留天数，默认取环境变量 {ACCESS_LOG_RETENTION_ENV} 或 {ACCESS_LOG_DEFAULT_RETENTION_DAYS}")
    parser.add_argument("--batch-size", type=int, default=ACCESS_LOG_BATCH_SIZE, help=f"每批删除行数（默认 {ACCESS_LOG_BATCH_SIZE}）")
    parser.add_argument("--dry-run", action="store_true", help="只统计将删除的行数，不实际删除")
    args = parser.parse_args()

    keep_days = args.days if args.days is not None else access_log_retention_days()
    removed = purge_access_logs(days=keep_days, batch_size=args.batch_size, dry_run=args.dry_run)
    prefix = "[dry-run] 将删除" if args.dry_run else "已删除"
    print(f"保留 {keep_days} 天，{prefix} {removed} 条访问日志")
    return 0


if __name__ == "__main__":
    sys.exit(main())
