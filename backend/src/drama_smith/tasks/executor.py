"""进程内 asyncio 任务执行器(D4)。

每用户 `Semaphore(max_tasks_per_user)` + 全局 `Semaphore(max_global_workers)`;`submit` 把已落
`pending` 的任务入队(`asyncio.create_task(_run)`)。`_run` 内 acquire 用户信号量(超限自然排队)
→ 置 `running` → 执行 `work(progress_cb)` → `finish`(succeeded / failed)。cancel 协作式
(`Task.cancel` → canceled);shutdown 把在跑的落 `interrupted`(与重启恢复同语义)。**不接 FileStore**
(M2 无富媒体;M3 引入 media 时扩展构造签名)。

**不耦合业务**:`work` 闭包由 service 注入(封装调图 / 落产物);executor 只调度 + 写 task 记录,
对业务无感(任务类型 / 产物结构均由 work 决定)。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drama_smith.core.errors import DomainError
from drama_smith.db.repositories import task_repo
from drama_smith.tasks.progress import ProgressCallback, make_progress_cb
from drama_smith.tasks.recover import recover_running
from drama_smith.tasks.states import CANCELED, FAILED, INTERRUPTED, SUCCEEDED

Work = Callable[[ProgressCallback], Awaitable[dict | None]]


def _error_dict(exc: Exception) -> dict[str, str]:
    """异常 → task.error 体能;domain 错误保留其 `code`,其余归 `internal_error`。"""
    if isinstance(exc, DomainError):
        return {"code": exc.code, "message": exc.message}
    return {"code": "internal_error", "message": str(exc) or exc.__class__.__name__}


class TaskExecutor:
    """单实例进程内执行器;lifespan 内构造一个,注入 `app.state.executor`。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        max_per_user: int,
        max_global: int,
    ) -> None:
        self._sf = session_factory
        self._max_per_user = max_per_user
        self._global_sem = asyncio.Semaphore(max_global)
        self._user_sems: dict[int, asyncio.Semaphore] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._shutting_down = False

    def _user_sem(self, user_id: int) -> asyncio.Semaphore:
        sem = self._user_sems.get(user_id)
        if sem is None:
            sem = asyncio.Semaphore(self._max_per_user)
            self._user_sems[user_id] = sem
        return sem

    async def submit(self, task_id: int, user_id: int, work: Work) -> asyncio.Task[None]:
        """把已落 `pending` 的任务入队;返回该 asyncio.Task(service 通常不等其完成)。"""
        atask = asyncio.create_task(self._run(task_id, user_id, work))
        self._tasks[task_id] = atask
        return atask

    async def cancel(self, task_id: int) -> bool:
        """协作式取消在跑任务;返回是否找到了未完成的任务。"""
        atask = self._tasks.get(task_id)
        if atask is None or atask.done():
            return False
        atask.cancel()
        return True

    async def _run(self, task_id: int, user_id: int, work: Work) -> None:
        try:
            async with self._user_sem(user_id), self._global_sem:
                await self._start(user_id, task_id)
                progress_cb = make_progress_cb(self._sf, user_id, task_id)
                output = await work(progress_cb)
                await self._finish(user_id, task_id, SUCCEEDED, output_refs=output)
        except asyncio.CancelledError:
            # 协作式取消:落终态后正常结束 task(shutdown 中 → interrupted,用户 cancel → canceled)。
            status = INTERRUPTED if self._shutting_down else CANCELED
            await self._finish(user_id, task_id, status)
        except Exception as exc:  # noqa: BLE001 — 执行器兜底:任何 work 异常都落 failed
            await self._finish(user_id, task_id, FAILED, error=_error_dict(exc))

    async def _start(self, user_id: int, task_id: int) -> None:
        async with self._sf() as session:
            await task_repo.start(session, user_id, task_id)
            await session.commit()

    async def _finish(
        self,
        user_id: int,
        task_id: int,
        status: str,
        *,
        error: dict[str, str] | None = None,
        output_refs: dict | None = None,
    ) -> None:
        async with self._sf() as session:
            await task_repo.finish(
                session,
                user_id,
                task_id,
                status=status,
                error=error,
                output_refs=output_refs,
            )
            await session.commit()

    async def recover_running(self) -> int:
        """启动恢复:残留 running → interrupted(lifespan 启动期调用)。"""
        return await recover_running(self._sf)

    async def shutdown(self) -> None:
        """优雅停止:取消在跑协程、落 interrupted(与重启恢复同语义)。"""
        self._shutting_down = True
        for atask in list(self._tasks.values()):
            if not atask.done():
                atask.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        self._shutting_down = False


__all__ = ["TaskExecutor", "Work"]
