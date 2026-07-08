"""启动恢复(D4):进程重启时把残留 `running` → `interrupted`(error.code=`restart_interrupted`)。

后台 asyncio task 随进程消失、无法续跑;恢复只把记录置为一致终态(`interrupted`),
前端轮询见 `interrupted` 即提示「可重试」(architecture §4.4)。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drama_smith.db.repositories import task_repo


async def recover_running(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """残留 `running` → `interrupted`;返回受影响行数。"""
    async with session_factory() as session:
        count = await task_repo.interrupt_running(session)
        await session.commit()
    return count


__all__ = ["recover_running"]
