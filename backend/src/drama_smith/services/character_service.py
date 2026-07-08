"""剧集角色用例编排(preset CRUD,事务边界在此,D1/D14)。

薄包装 `episode_character_repo`(已具备 `get/create/update/delete + list_by_episode/
bulk_create`);本服务只加 commit 边界 + 嵌套资源归属收口(`/episodes/:eid/characters/:cid`
须校验 `cid` 属于 `eid`)。`source` 由 repo 固定为 `preset`(分析产角色不经此路径)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import NotFound
from drama_smith.db.models import EpisodeCharacter
from drama_smith.db.repositories import episode_character_repo, episode_repo


async def list_characters(
    session: AsyncSession, user_id: int, episode_id: int
) -> list[EpisodeCharacter]:
    """列某剧集全部角色(preset + analysis;按 `sort_order`、`id`)。"""
    return await episode_character_repo.list_by_episode(session, user_id, episode_id)


async def get_character(
    session: AsyncSession, user_id: int, episode_id: int, character_id: int
) -> EpisodeCharacter:
    """取单角色;校验 `character_id` 属于 `episode_id`(嵌套资源 404 不泄露存在)。"""
    await episode_repo.get(session, user_id, episode_id)
    character = await episode_character_repo.get(session, user_id, character_id)
    if character.episode_id != episode_id:
        raise NotFound("Episode character not found")
    return character


async def create_character(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    *,
    name: str,
    role_type: str | None = None,
    persona: str | None = None,
    motivation: str | None = None,
    traits: list[Any] | None = None,
    appearance_desc: str | None = None,
    sort_order: int = 0,
) -> EpisodeCharacter:
    """新建预置角色(`source='preset'`;归属经 episode 校验)。"""
    character = await episode_character_repo.create(
        session,
        user_id,
        episode_id,
        name=name,
        role_type=role_type,
        persona=persona,
        motivation=motivation,
        traits=traits,
        appearance_desc=appearance_desc,
        sort_order=sort_order,
    )
    await session.commit()
    return character


async def update_character(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    character_id: int,
    *,
    fields: dict[str, Any],
) -> EpisodeCharacter:
    """按字段更新(白名单过滤);校验嵌套归属。"""
    character = await get_character(session, user_id, episode_id, character_id)
    updated = await episode_character_repo.update(session, character, fields=fields)
    await session.commit()
    return updated


async def delete_character(
    session: AsyncSession, user_id: int, episode_id: int, character_id: int
) -> None:
    """删除预置角色(物理删;`shot_characters` FK CASCADE 清理出场引用)。"""
    character = await get_character(session, user_id, episode_id, character_id)
    await episode_character_repo.delete(session, character)
    await session.commit()
