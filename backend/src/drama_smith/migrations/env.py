"""Alembic 迁移环境(async,asyncmy 驱动)。

设计依据(`design.md` D13):src layout 路径 + async 模板(`run_sync`)+ autogenerate
前 import 全部模型(经 `drama_smith.db.models` 注册到 `Base.metadata`)。
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# 双重保险:把 <backend>/src 纳入 sys.path(alembic.ini 的 prepend_sys_path 通常已处理)。
_src_dir = Path(__file__).resolve().parents[2]
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from drama_smith.core.config import get_settings  # noqa: E402
from drama_smith.db import models as _models  # noqa: E402,F401  注册模型到 metadata
from drama_smith.db.base import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DSN 经 Settings 统一注入(不写死在 ini)。
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式:生成 SQL 脚本,不连库。"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """在线模式(async):经 asyncmy 连接,run_sync 执行迁移逻辑。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
