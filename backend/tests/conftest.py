"""集成测试夹具:专用测试库 + 事务隔离 + HTTP 客户端。

策略(`design.md` D11):session 级建一个专用测试库(默认从 `DS_DATABASE_URL` 派生
`<db>_test`,可经 `DS_TEST_DATABASE_URL` 覆盖),经 `override_settings` 把懒加载引擎
工厂重定向到该库,再在进程内 `alembic upgrade head` 建表(任务 6.1 要求)。
每个用例后 `TRUNCATE` 所有表做隔离,保证用例独立、可重复。

- 测试库创建 / 迁移 / 引擎释放均在 **同步 session 夹具** 中以 `asyncio.run` 顺序执行,
  避开与 pytest-asyncio 函数级事件循环的嵌套。
- `client` 复用真实 `get_session` 依赖(指向测试库),故整套 DB 层被真正覆盖。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config as AlembicConfig
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from drama_smith.core.config import Settings, override_settings
from drama_smith.db.base import Base, dispose_engine, get_engine, get_session_factory
from drama_smith.db.models import RefreshToken, User  # noqa: F401  注册到 metadata
from drama_smith.main import create_app
from tests.helpers import unique_username

_BACKEND_DIR = Path(__file__).resolve().parents[1]


def _test_dsn() -> str:
    """测试库 DSN。

    优先取 `DS_TEST_DATABASE_URL`;否则从当前 `Settings().database_url` 派生
    `<db>_test`(保留原 query,如 `charset=utf8mb4`)。读 `Settings()`(非 `get_settings`)
    以避开 `override_settings`,拿到原始配置。
    """
    explicit = os.environ.get("DS_TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = Settings().database_url
    parts = urlsplit(base)
    base_db = parts.path.strip("/").split("?")[0]
    test_db = f"{base_db}_test"
    return urlunsplit((parts.scheme, parts.netloc, f"/{test_db}", parts.query, parts.fragment))


def _server_dsn(dsn: str) -> str:
    """去掉库名的「服务器级」DSN(用于 `CREATE DATABASE`)。"""
    parts = urlsplit(dsn)
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


async def _ensure_database(test_dsn: str) -> str:
    """`CREATE DATABASE IF NOT EXISTS`(幂等);utf8mb4 与模型 `__table_args__` 对齐。"""
    parts = urlsplit(test_dsn)
    test_db = parts.path.strip("/").split("?")[0]
    engine = create_async_engine(_server_dsn(test_dsn), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{test_db}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                )
            )
            await conn.commit()
    finally:
        await engine.dispose()
    return test_dsn


def _run_migrations() -> None:
    """进程内 `alembic upgrade head`(env.py 经 `get_settings()` 读到已覆盖的测试 DSN)。"""
    cfg = AlembicConfig(str(_BACKEND_DIR / "alembic.ini"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _setup_test_db() -> Iterator[None]:
    """session 级:建测试库 → 覆盖 settings → 释放旧引擎 → 建表;结束释放引擎并还原。"""
    test_dsn = _test_dsn()
    asyncio.run(_ensure_database(test_dsn))
    override_settings(lambda: Settings(database_url=test_dsn, environment="test"))
    asyncio.run(dispose_engine())  # 丢弃可能已缓存的原引擎,迫使按新 settings 重建
    _run_migrations()
    yield
    asyncio.run(dispose_engine())
    override_settings(None)


@pytest_asyncio.fixture
async def db_engine() -> AsyncEngine:
    """指向测试库的引擎(get_engine 经 override_settings 已重定向)。"""
    return get_engine()


@pytest_asyncio.fixture(autouse=True)
async def _truncate_tables(db_engine: AsyncEngine) -> AsyncIterator[None]:
    """每条用例后清空所有表(重置 AUTO_INCREMENT),保证用例间状态独立。"""
    yield
    async with db_engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in Base.metadata.sorted_tables:
            await conn.execute(text(f"TRUNCATE TABLE `{table.name}`"))
        await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """ASGI 测试客户端;复用真实 `get_session`(指向测试库),不触发 lifespan。"""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """直连测试库的会话,供用例直接读写底层状态(如改 `locked_until` 模拟解锁)。"""
    factory: async_sessionmaker[AsyncSession] = get_session_factory()
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def register_user(
    client: AsyncClient,
) -> Callable[..., Any]:
    """返回一个协程:按给定账密注册,断言 201 并返回信封内 `data`(含令牌)。"""

    async def _register(
        username: str | None = None,
        password: str = "Sup3rSecret!",
    ) -> dict[str, Any]:
        body = {"username": username or unique_username(), "password": password}
        resp = await client.post("/api/auth/register", json=body)
        assert resp.status_code == 201, resp.text
        data: dict[str, Any] = resp.json()["data"]
        return data

    return _register
