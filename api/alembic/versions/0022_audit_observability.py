"""Audit observability: request tracing columns and full access log.

审计可观测性：为业务审计补上请求上下文与成败标记，并新增请求层访问日志表。
该表由 API 中间件用独立会话写入，因此不受业务事务回滚影响，
使「越权被拒」「版本冲突」「登录失败」等未成功的动作也能留痕。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0022_audit_observability"
down_revision = "0021_optional_reminder_note"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 业务审计扩展：全部可空，旧代码与历史数据无需迁移。
    op.add_column("pkm_audit_events", sa.Column("request_id", postgresql.UUID(as_uuid=True)))
    op.add_column("pkm_audit_events", sa.Column("actor_id", postgresql.UUID(as_uuid=True)))
    op.add_column("pkm_audit_events", sa.Column("outcome", sa.SmallInteger()))
    op.add_column("pkm_audit_events", sa.Column("before", postgresql.JSONB()))
    op.add_column("pkm_audit_events", sa.Column("after", postgresql.JSONB()))
    op.create_index("ix_audit_request", "pkm_audit_events", ["request_id"])
    op.create_index(
        "ix_audit_user_action_created",
        "pkm_audit_events",
        ["user_id", "action", "created_at"],
    )

    # 请求层访问日志：未登录请求同样记录，user_id 为空。
    op.create_table(
        "pkm_access_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("path", sa.String(255), nullable=False),
        sa.Column("status_code", sa.SmallInteger(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(45)),
        sa.Column("user_agent", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_access_request", "pkm_access_logs", ["request_id"])
    op.create_index("ix_access_user_created", "pkm_access_logs", ["user_id", "created_at"])
    op.create_index("ix_access_created", "pkm_access_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("pkm_access_logs")
    op.drop_index("ix_audit_user_action_created", table_name="pkm_audit_events")
    op.drop_index("ix_audit_request", table_name="pkm_audit_events")
    for column in ("after", "before", "outcome", "actor_id", "request_id"):
        op.drop_column("pkm_audit_events", column)
