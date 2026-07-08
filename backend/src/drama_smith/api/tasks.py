"""任务端点:`/api/tasks`(读 + 协作式取消)。

接口层只解析参数 + 组装响应;用例编排在 `task_service`。`cancel` 为协作式:`executor.cancel`
置取消请求,终态落库由执行器后台异步完成(`_run` 内 CancelledError → `_finish(canceled)`)。
故响应里的 task 可能仍显 `pending`/`running`——前端轮询 `GET .../tasks/:id` 确认 `canceled`。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from drama_smith.api.deps import ExecutorDep, SessionDep, UserDep
from drama_smith.api.schemas import Envelope, ErrorResponse, TaskPublic
from drama_smith.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "任务不存在或越权访问(not_found)"}
}


@router.get(
    "/{task_id}",
    summary="获取任务",
    response_model=Envelope[TaskPublic],
    responses={**_NOT_FOUND},
)
async def get_task(task_id: int, user: UserDep, session: SessionDep) -> Envelope[TaskPublic]:
    task = await task_service.get_task(session, user.id, task_id)
    return Envelope(data=TaskPublic.model_validate(task))


@router.post(
    "/{task_id}/cancel",
    summary="取消任务",
    description="协作式取消在途(pending/running)任务;终态任务 → 409 invalid_state。",
    response_model=Envelope[TaskPublic],
    responses={
        **_NOT_FOUND,
        409: {"model": ErrorResponse, "description": "非可取消态(invalid_state)"},
    },
)
async def cancel_task(
    task_id: int, user: UserDep, session: SessionDep, executor: ExecutorDep
) -> Envelope[TaskPublic]:
    task = await task_service.cancel_task(session, user.id, task_id, executor=executor)
    return Envelope(data=TaskPublic.model_validate(task))
