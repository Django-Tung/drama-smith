"""任务仓储(持久化、可恢复,[FR-A11](../../requirements/features/analysis.md))。

事务边界在 services 层(M0 D14);`user_id` 强制过滤(M0 D6 隔离),越权 → `NotFound`。
`interrupt_running` 为**全局**启动恢复(不带 user_id):进程重启时把残留 `running` 置
`interrupted`(D4),使重启后状态自洽。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import NotFound
from drama_smith.db.base import utcnow
from drama_smith.db.models import Task

_UNSET: Any = object()


async def create(
    session: AsyncSession,
    user_id: int,
    *,
    episode_id: int | None,
    type: str,
    input_snapshot: dict | None = None,
    trigger: str = "single",
) -> Task:
    """新建任务(`status='pending'`、`progress=0`);`episode_id` 可空(跨剧集汇总)。"""
    task = Task(
        user_id=user_id,
        episode_id=episode_id,
        type=type,
        status="pending",
        trigger=trigger,
        input_snapshot=input_snapshot,
    )
    session.add(task)
    await session.flush()
    await session.refresh(task)
    return task


async def get(session: AsyncSession, user_id: int, task_id: int) -> Task:
    """按 id 取任务(强制 `user_id`);无命中 / 越权 → `NotFound`。"""
    stmt = select(Task).where(Task.id == task_id, Task.user_id == user_id)
    task: Task | None = (await session.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise NotFound("Task not found")
    return task


async def set_status(
    session: AsyncSession, user_id: int, task_id: int, status: str
) -> None:
    """`UPDATE ... WHERE id AND user_id`;越权 / 不存在 → `NotFound`。"""
    result = await session.execute(
        sql_update(Task)
        .where(Task.id == task_id, Task.user_id == user_id)
        .values(status=status)
    )
    if result.rowcount == 0:
        raise NotFound("Task not found")


async def start(session: AsyncSession, user_id: int, task_id: int) -> None:
    """置 `running` 并记 `started_at`(执行器 acquire 信号量后调用)。"""
    result = await session.execute(
        sql_update(Task)
        .where(Task.id == task_id, Task.user_id == user_id)
        .values(status="running", started_at=utcnow())
    )
    if result.rowcount == 0:
        raise NotFound("Task not found")


async def update_progress(
    session: AsyncSession,
    user_id: int,
    task_id: int,
    progress: int,
    stage: str | None = _UNSET,
) -> None:
    """写进度记录(REST 可读);`stage` 缺省不改动。"""
    values: dict[str, Any] = {"progress": progress}
    if stage is not _UNSET:
        values["stage"] = stage
    await session.execute(
        sql_update(Task)
        .where(Task.id == task_id, Task.user_id == user_id)
        .values(**values)
    )


async def finish(
    session: AsyncSession,
    user_id: int,
    task_id: int,
    *,
    status: str,
    error: dict | None = None,
    output_refs: dict | None = None,
) -> None:
    """置终态(`succeeded`/`failed`/`canceled`)并记 `finished_at`。"""
    values: dict[str, Any] = {"status": status, "finished_at": utcnow()}
    if error is not None:
        values["error"] = error
    if output_refs is not None:
        values["output_refs"] = output_refs
    await session.execute(
        sql_update(Task)
        .where(Task.id == task_id, Task.user_id == user_id)
        .values(**values)
    )


async def interrupt_running(session: AsyncSession) -> int:
    """启动恢复:残留 `running` → `interrupted`(D4)。返回受影响行数。"""
    result = await session.execute(
        sql_update(Task)
        .where(Task.status == "running")
        .values(
            status="interrupted",
            error={
                "code": "restart_interrupted",
                "message": "Interrupted by process restart",
            },
            finished_at=utcnow(),
        )
    )
    return int(result.rowcount or 0)
