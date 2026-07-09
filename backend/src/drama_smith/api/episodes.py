"""剧集端点:`/api/episodes`(剧集 CRUD + 剧本版本 + AI 优化)。

接口层只解析参数 + 组装响应;用例编排、事务边界、归属校验在 services。剧本版本 append-only:
`PUT .../script` 产 `source='input'` 版本并移 current 指针;`optimize` 为异步(202 + 轮询);
`select`(=accept=revert)移指针、`reject` 显式 no-op(D6)。错误统一抛 `DomainError` 子类。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from drama_smith.api.deps import ExecutorDep, MekDep, SessionDep, UserDep
from drama_smith.api.schemas import (
    Envelope,
    EpisodePublic,
    EpisodeUpdate,
    ErrorResponse,
    ScriptPublic,
    ScriptUpsert,
    ScriptVersionPublic,
    TaskPublic,
)
from drama_smith.services import episode_service, script_service

router = APIRouter(prefix="/episodes", tags=["episodes"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "剧集不存在或越权访问(not_found)"}
}
_ASYNC_ERR: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorResponse,
        "description": "无 active 文本配置(model_not_configured)/ 已有在途拆解(invalid_state)",
    },
    422: {"model": ErrorResponse, "description": "剧集尚无剧本(script_required)"},
}


@router.get(
    "/{episode_id}",
    summary="获取剧集",
    response_model=Envelope[EpisodePublic],
    responses={**_NOT_FOUND},
)
async def get_episode(
    episode_id: int, user: UserDep, session: SessionDep
) -> Envelope[EpisodePublic]:
    episode = await episode_service.get_episode(session, user.id, episode_id)
    return Envelope(data=EpisodePublic.model_validate(episode))


@router.put(
    "/{episode_id}",
    summary="更新剧集",
    description="仅转发显式给出的字段;缺省字段不动、显式 null 清空 `style_preset`。",
    response_model=Envelope[EpisodePublic],
    responses={**_NOT_FOUND},
)
async def update_episode(
    episode_id: int, body: EpisodeUpdate, user: UserDep, session: SessionDep
) -> Envelope[EpisodePublic]:
    fields = body.model_fields_set
    provided: dict[str, Any] = {}
    if "title" in fields:
        provided["title"] = body.title
    if "aspect_ratio" in fields:
        provided["aspect_ratio"] = body.aspect_ratio
    if "style_preset" in fields:
        provided["style_preset"] = body.style_preset
    if "status" in fields:
        provided["status"] = body.status
    episode = await episode_service.update_episode(session, user.id, episode_id, **provided)
    return Envelope(data=EpisodePublic.model_validate(episode))


@router.delete(
    "/{episode_id}",
    summary="删除剧集(软删)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND},
)
async def delete_episode(episode_id: int, user: UserDep, session: SessionDep) -> None:
    await episode_service.delete_episode(session, user.id, episode_id)


@router.get(
    "/{episode_id}/script",
    summary="获取剧本容器",
    description="剧本容器(含 `current_version_id`);供前端标记当前版本。无容器 → 404。",
    response_model=Envelope[ScriptPublic],
    responses={**_NOT_FOUND},
)
async def get_script(episode_id: int, user: UserDep, session: SessionDep) -> Envelope[ScriptPublic]:
    script = await script_service.get_script(session, user.id, episode_id)
    return Envelope(data=ScriptPublic.model_validate(script))


@router.put(
    "/{episode_id}/script",
    summary="写入剧本正文",
    description="追加 `source='input'` 版本并移 current 指针(整版覆盖)。",
    response_model=Envelope[ScriptVersionPublic],
    responses={**_NOT_FOUND},
)
async def upsert_script(
    episode_id: int, body: ScriptUpsert, user: UserDep, session: SessionDep
) -> Envelope[ScriptVersionPublic]:
    version = await script_service.upsert_script(
        session, user.id, episode_id, content=body.content, format=body.format
    )
    return Envelope(data=ScriptVersionPublic.model_validate(version))


@router.get(
    "/{episode_id}/script/versions",
    summary="列出剧本版本",
    response_model=Envelope[list[ScriptVersionPublic]],
    responses={**_NOT_FOUND},
)
async def list_script_versions(
    episode_id: int, user: UserDep, session: SessionDep
) -> Envelope[list[ScriptVersionPublic]]:
    versions = await script_service.list_versions(session, user.id, episode_id)
    return Envelope(data=[ScriptVersionPublic.model_validate(v) for v in versions])


@router.post(
    "/{episode_id}/script/optimize",
    summary="发起 AI 优化(copy-edit)",
    description="异步润色当前剧本 → 产 `source='optimize'` 新版本(**不移指针**)。202 + 轮询任务。",
    response_model=Envelope[TaskPublic],
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_ASYNC_ERR},
)
async def optimize_script(
    episode_id: int,
    user: UserDep,
    session: SessionDep,
    mek: MekDep,
    executor: ExecutorDep,
) -> Envelope[TaskPublic]:
    task = await script_service.optimize_script(
        session, user.id, episode_id, executor=executor, mek=mek
    )
    return Envelope(data=TaskPublic.model_validate(task))


@router.post(
    "/{episode_id}/script/versions/{version_id}/select",
    summary="采纳 / 回退到指定版本",
    description="移 current 指针到指定版本(accept=revert,D6)。",
    response_model=Envelope[ScriptVersionPublic],
    responses={**_NOT_FOUND},
)
async def select_version(
    episode_id: int, version_id: int, user: UserDep, session: SessionDep
) -> Envelope[ScriptVersionPublic]:
    await script_service.select_version(session, user.id, episode_id, version_id)
    version = await script_service.get_version(session, user.id, version_id)
    return Envelope(data=ScriptVersionPublic.model_validate(version))


@router.post(
    "/{episode_id}/script/versions/{version_id}/reject",
    summary="拒绝采纳",
    description="不动指针、版本保留(可回看/回退)。显式 no-op(D6)。",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND},
)
async def reject_version(
    episode_id: int, version_id: int, user: UserDep, session: SessionDep
) -> None:
    await script_service.reject_version(session, user.id, episode_id, version_id)
