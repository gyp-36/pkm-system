"""Alembic environment shared with the containerized application."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, inspect, pool, text

from app.core.db import Base
import app.core.models  # noqa: F401 - 注册模型元数据


config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"].replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=os.environ["DATABASE_URL"], target_metadata=target_metadata, literal_binds=True, version_table="pkm_alembic_version")
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        inspector = inspect(connection)
        legacy = inspector.has_table("alembic_version")
        current = inspector.has_table("pkm_alembic_version")
        if legacy and current:
            raise RuntimeError("Both Alembic version tables exist; resolve this manually before migration")
        if legacy:
            connection.execute(text("ALTER TABLE alembic_version RENAME TO pkm_alembic_version"))
        # 检查操作会开启事务；在 Alembic 接管 DDL 事务之前先结束该事务。
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, version_table="pkm_alembic_version")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
