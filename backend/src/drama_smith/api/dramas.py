"""剧目端点:`/api/dramas`(含剧集子集合)。

接口层只解析参数 + 组装 `{data,meta}` 响应;用例编排、事务边界、归属校验在 services。
越权 / 不存在 / 已删 → `NotFound`(404,不泄露存在性)。错误统一抛 `DomainError` 子类,
经全局处理器映射,路由内不写 try/except。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from drama_smith.api.deps import SessionDep, UserDep
from drama_smith.api.schemas import (
    DramaCreate,
    DramaPublic,
    DramaRename,
    Envelope,
    EpisodeCreate,
    EpisodePublic,
    ErrorResponse,
)
from drama_smith.services import drama_service, episode_service

router = APIRouter(prefix="/dramas", tags=["dramas"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "剧目不存在或越权访问(not_found)"}
}


@router.post(
    "",
    summary="新建剧目",
    response_model=Envelope[DramaPublic],
    status_code=status.HTTP_201_CREATED,
)
async def create_drama(
    body: DramaCreate, user: UserDep, session: SessionDep
) -> Envelope[DramaPublic]:
    drama = await drama_service.create_drama(session, user.id, name=body.name)
    return Envelope(data=DramaPublic.model_validate(drama))


@router.get("", summary="列出我的剧目", response_model=Envelope[list[DramaPublic]])
async def list_dramas(user: UserDep, session: SessionDep) -> Envelope[list[DramaPublic]]:
    dramas = await drama_service.list_dramas(session, user.id)
    return Envelope(data=[DramaPublic.model_validate(d) for d in dramas])


@router.get(
    "/{drama_id}",
    summary="获取剧目",
    response_model=Envelope[DramaPublic],
    responses={**_NOT_FOUND},
)
async def get_drama(drama_id: int, user: UserDep, session: SessionDep) -> Envelope[DramaPublic]:
    drama = await drama_service.get_drama(session, user.id, drama_id)
    return Envelope(data=DramaPublic.model_validate(drama))


@router.put(
    "/{drama_id}",
    summary="重命名剧目",
    response_model=Envelope[DramaPublic],
    responses={**_NOT_FOUND},
)
async def rename_drama(
    drama_id: int, body: DramaRename, user: UserDep, session: SessionDep
) -> Envelope[DramaPublic]:
    drama = await drama_service.rename_drama(session, user.id, drama_id, name=body.name)
    return Envelope(data=DramaPublic.model_validate(drama))


@router.delete(
    "/{drama_id}",
    summary="删除剧目(软删)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND},
)
async def delete_drama(drama_id: int, user: UserDep, session: SessionDep) -> None:
    await drama_service.delete_drama(session, user.id, drama_id)


@router.get(
    "/{drama_id}/episodes",
    summary="列出剧目下的剧集",
    response_model=Envelope[list[EpisodePublic]],
    responses={**_NOT_FOUND},
)
async def list_episodes(
    drama_id: int, user: UserDep, session: SessionDep
) -> Envelope[list[EpisodePublic]]:
    episodes = await episode_service.list_episodes(session, user.id, drama_id)
    return Envelope(data=[EpisodePublic.model_validate(e) for e in episodes])


@router.post(
    "/{drama_id}/episodes",
    summary="新建剧集",
    response_model=Envelope[EpisodePublic],
    status_code=status.HTTP_201_CREATED,
    responses={**_NOT_FOUND},
)
async def create_episode(
    drama_id: int, body: EpisodeCreate, user: UserDep, session: SessionDep
) -> Envelope[EpisodePublic]:
    episode = await episode_service.create_episode(
        session,
        user.id,
        drama_id,
        title=body.title,
        aspect_ratio=body.aspect_ratio,
        style_preset=body.style_preset,
    )
    return Envelope(data=EpisodePublic.model_validate(episode))
