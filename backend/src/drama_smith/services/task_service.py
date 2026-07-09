"""任务用例编排(读 + 协作式取消,事务边界在此)。

薄包装 `task_repo`;`cancel_task` 校验状态可取消(在途 `pending`/`running`)后交执行器
协作式取消(`executor.cancel` → `_run` 内 `CancelledError` → `_finish(canceled)` 异步落库)。
返回的 task 可能仍显在途态——前端轮询 `GET /tasks/:id` 至 `canceled`(异步契约,见 D4)。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import InvalidState
from drama_smith.db.models import Task
from drama_smith.db.repositories import task_repo
from drama_smith.tasks import INFLIGHT, TaskExecutor


async def get_task(session: AsyncSession, user_id: int, task_id: int) -> Task:
    """取单任务(强制 `user_id`;越权 / 不存在 → `NotFound`)。"""
    return await task_repo.get(session, user_id, task_id)


async def cancel_task(
    session: AsyncSession,
    user_id: int,
    task_id: int,
    *,
    executor: TaskExecutor,
) -> Task:
    """协作式取消在途任务;终态任务 → `InvalidState`(409,不可再取消)。

    `executor.cancel` 仅置取消请求(`Task.cancel`);终态落库由执行器后台 `_run` 异步完成,
    故返回的 task 可能仍显 `pending`/`running`——前端轮询确认。
    """
    task = await task_repo.get(session, user_id, task_id)
    if task.status not in INFLIGHT:
        raise InvalidState(
            "Task is not in a cancelable state",
            details={"reason": "not_cancelable", "status": task.status},
        )
    await executor.cancel(task_id)
    return task


async def find_inflight(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    *,
    type: str,
) -> Task | None:
    """该剧集最近一个在途(`pending`/`running`)任务(按 `type` 过滤);无则 None。

    供前端切 tab / 刷新 / 重进页面时查在途任务(如 `optimize`)以恢复轮询——替代
    sessionStorage(后者会因标签关闭、清缓存等丢失)。后端「在途任务」是单一事实源
    (与 analyze 经 `summary.inflight_task` 续跑同理)。薄转调
    `task_repo.find_inflight_by_episode`。
    """
    return await task_repo.find_inflight_by_episode(session, user_id, episode_id, type=type)
