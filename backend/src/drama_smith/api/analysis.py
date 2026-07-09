"""分析端点:`/api/episodes/:id/analyze|analysis`(拆解异步 + 双语义读 + 切换)。

接口层只解析参数 + 组装响应;用例编排在 `analysis_service`。`analyze` 为异步(202 + 轮询):
门禁(无 active 配置 → 409 `model_not_configured`)、无剧本(422 `script_required`)、串行约束
(在途 → 409 `invalid_state`)。`GET .../analysis` 返 D11 双语义(上次结果 + 在途任务 + 过期标记)。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from drama_smith.api.deps import ExecutorDep, MekDep, SessionDep, UserDep
from drama_smith.api.schemas import (
    AnalysisCurrentPatch,
    AnalysisPublic,
    AnalysisSummary,
    Envelope,
    ErrorResponse,
    TaskPublic,
)
from drama_smith.core.errors import NotFound
from drama_smith.services import analysis_service

router = APIRouter(prefix="/episodes", tags=["analysis"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "剧集不存在或越权访问(not_found)"}
}
_ANALYZE_ERR: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorResponse,
        "description": "无 active 文本配置(model_not_configured)/ 已有在途拆解(invalid_state)",
    },
    422: {"model": ErrorResponse, "description": "剧集尚无剧本(script_required)"},
}


@router.post(
    "/{episode_id}/analyze",
    summary="发起结构化拆解",
    description="异步跑分析图 → 落库(角色/分镜/出场)+ 移 current 指针。202 + 轮询任务。",
    response_model=Envelope[TaskPublic],
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_ANALYZE_ERR},
)
async def analyze(
    episode_id: int,
    user: UserDep,
    session: SessionDep,
    mek: MekDep,
    executor: ExecutorDep,
) -> Envelope[TaskPublic]:
    task = await analysis_service.analyze(session, user.id, episode_id, executor=executor, mek=mek)
    return Envelope(data=TaskPublic.model_validate(task))


@router.get(
    "/{episode_id}/analysis",
    summary="读取分析状态(双语义)",
    description=(
        "`current_analysis`(上次结果)+ `inflight_task`(在途)+ `stale_flag`(剧本已改,建议重拆)。"
    ),
    response_model=Envelope[AnalysisSummary],
    responses={**_NOT_FOUND},
)
async def get_analysis(
    episode_id: int, user: UserDep, session: SessionDep
) -> Envelope[AnalysisSummary]:
    d = await analysis_service.get_analysis(session, user.id, episode_id)
    summary = AnalysisSummary(
        current_analysis=(
            AnalysisPublic.model_validate(d["current_analysis"])
            if d["current_analysis"] is not None
            else None
        ),
        inflight_task=(
            TaskPublic.model_validate(d["inflight_task"])
            if d["inflight_task"] is not None
            else None
        ),
        stale_flag=d["stale_flag"],
    )
    return Envelope(data=summary)


@router.get(
    "/{episode_id}/analyses",
    summary="列出剧集的分析历史",
    description="全部分析(新→旧,append-only),供「切回历史分镜」picker(D11)。",
    response_model=Envelope[list[AnalysisPublic]],
    responses={**_NOT_FOUND},
)
async def list_analyses(
    episode_id: int, user: UserDep, session: SessionDep
) -> Envelope[list[AnalysisPublic]]:
    items = await analysis_service.list_history(session, user.id, episode_id)
    return Envelope(data=[AnalysisPublic.model_validate(a) for a in items])


@router.patch(
    "/{episode_id}/analysis/current",
    summary="切换当前分析",
    description="移 `current_analysis_id` 到指定历史 analysis(D11;须属本剧集)。",
    response_model=Envelope[AnalysisPublic],
    responses={**_NOT_FOUND},
)
async def select_current_analysis(
    episode_id: int,
    body: AnalysisCurrentPatch,
    user: UserDep,
    session: SessionDep,
) -> Envelope[AnalysisPublic]:
    await analysis_service.select_current_analysis(session, user.id, episode_id, body.analysis_id)
    d = await analysis_service.get_analysis(session, user.id, episode_id)
    current = d["current_analysis"]
    if current is None:  # 不可达:刚 select 成功,指针已指
        raise NotFound("Analysis not found")
    return Envelope(data=AnalysisPublic.model_validate(current))
