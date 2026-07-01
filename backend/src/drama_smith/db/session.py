"""请求级异步会话依赖。

事务边界在 services 层(`design.md` D14);本依赖只负责会话生命周期,
不在此 commit/rollback,避免与 services 用例边界争抢事务。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.db.base import get_session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖:yield 一个请求级 `AsyncSession`,作用域结束自动关闭。"""
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session
