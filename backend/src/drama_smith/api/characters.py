"""剧集角色端点:`/api/episodes/:id/characters`(preset CRUD)。

接口层只解析参数 + 组装响应;用例编排、事务边界、归属校验在 `character_service`(薄包装
`episode_character_repo`)。preset 角色可经 API 增删改;分析产角色(`source='analysis'`)
只读(由拆解落库,不可经此改)。嵌套资源 `:cid` 须属 `:id`(否则 404 不泄露存在)。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from drama_smith.api.deps import SessionDep, UserDep
from drama_smith.api.schemas import (
    CharacterCreate,
    CharacterUpdate,
    Envelope,
    EpisodeCharacterPublic,
    ErrorResponse,
)
from drama_smith.services import character_service

router = APIRouter(prefix="/episodes", tags=["characters"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "剧集 / 角色不存在或越权访问(not_found)"}
}


@router.get(
    "/{episode_id}/characters",
    summary="列出剧集角色",
    response_model=Envelope[list[EpisodeCharacterPublic]],
    responses={**_NOT_FOUND},
)
async def list_characters(
    episode_id: int, user: UserDep, session: SessionDep
) -> Envelope[list[EpisodeCharacterPublic]]:
    chars = await character_service.list_characters(session, user.id, episode_id)
    return Envelope(data=[EpisodeCharacterPublic.model_validate(c) for c in chars])


@router.post(
    "/{episode_id}/characters",
    summary="新建预置角色",
    response_model=Envelope[EpisodeCharacterPublic],
    status_code=status.HTTP_201_CREATED,
    responses={**_NOT_FOUND},
)
async def create_character(
    episode_id: int, body: CharacterCreate, user: UserDep, session: SessionDep
) -> Envelope[EpisodeCharacterPublic]:
    char = await character_service.create_character(
        session,
        user.id,
        episode_id,
        name=body.name,
        role_type=body.role_type,
        persona=body.persona,
        motivation=body.motivation,
        traits=body.traits,
        appearance_desc=body.appearance_desc,
        sort_order=body.sort_order,
    )
    return Envelope(data=EpisodeCharacterPublic.model_validate(char))


@router.get(
    "/{episode_id}/characters/{character_id}",
    summary="获取角色",
    response_model=Envelope[EpisodeCharacterPublic],
    responses={**_NOT_FOUND},
)
async def get_character(
    episode_id: int, character_id: int, user: UserDep, session: SessionDep
) -> Envelope[EpisodeCharacterPublic]:
    char = await character_service.get_character(session, user.id, episode_id, character_id)
    return Envelope(data=EpisodeCharacterPublic.model_validate(char))


@router.put(
    "/{episode_id}/characters/{character_id}",
    summary="更新角色",
    description="仅转发显式给出的字段(白名单过滤);缺省不动、显式 null 清空可空字段。",
    response_model=Envelope[EpisodeCharacterPublic],
    responses={**_NOT_FOUND},
)
async def update_character(
    episode_id: int,
    character_id: int,
    body: CharacterUpdate,
    user: UserDep,
    session: SessionDep,
) -> Envelope[EpisodeCharacterPublic]:
    provided: dict[str, Any] = {k: getattr(body, k) for k in body.model_fields_set}
    char = await character_service.update_character(
        session, user.id, episode_id, character_id, fields=provided
    )
    return Envelope(data=EpisodeCharacterPublic.model_validate(char))


@router.delete(
    "/{episode_id}/characters/{character_id}",
    summary="删除角色",
    description="物理删;`shot_characters` FK CASCADE 清理出场引用。",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND},
)
async def delete_character(
    episode_id: int, character_id: int, user: UserDep, session: SessionDep
) -> None:
    await character_service.delete_character(session, user.id, episode_id, character_id)
