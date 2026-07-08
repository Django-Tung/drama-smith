"""进度回调工厂(D4):work 内调用 → 写 `task.progress` / `task.stage`(REST 可读)。

执行器的 work 闭包跑在后台 asyncio task,**不复用 service 的请求 session**;故每次进度写都
开独立 session → `task_repo.update_progress` → commit,保证进度记录可被 `GET /api/tasks/:id` 读到。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drama_smith.db.repositories import task_repo

ProgressCallback = Callable[[int, str | None], Awaitable[None]]


def make_progress_cb(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: int,
    task_id: int,
) -> ProgressCallback:
    """构造 `async (progress, stage=None)` 回调:每次开新 session 写记录后提交。"""

    async def cb(progress: int, stage: str | None = None) -> None:
        async with session_factory() as session:
            await task_repo.update_progress(session, user_id, task_id, progress, stage)
            await session.commit()

    return cb


__all__ = ["ProgressCallback", "make_progress_cb"]
