"""剧集角色仓储(归属经 `episode → drama → user`)。

事务边界在 services 层(M0 D14);越权 → `NotFound`。`bulk_create` 供拆解产角色写入,
**返回插入行 id 列表**(供 service 建 name→id 映射解析分镜出场,D13);`source` 区分预置/拆解。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import NotFound
from drama_smith.db.models import Drama, Episode, EpisodeCharacter
from drama_smith.db.repositories import episode_repo

# 角色可设字段(bulk_create / create 过滤白名单,屏蔽未知键)。
_CHARACTER_FIELDS = {
    "name",
    "role_type",
    "persona",
    "motivation",
    "traits",
    "appearance_desc",
    "sort_order",
}


async def list_by_episode(
    session: AsyncSession, user_id: int, episode_id: int
) -> list[EpisodeCharacter]:
    """列某剧集全部角色(归属经 episode→drama 校验);按 `sort_order`、`id`。"""
    await episode_repo.get(session, user_id, episode_id)
    stmt = (
        select(EpisodeCharacter)
        .join(Episode, EpisodeCharacter.episode_id == Episode.id)
        .join(Drama, Episode.drama_id == Drama.id)
        .where(
            EpisodeCharacter.episode_id == episode_id,
            Drama.user_id == user_id,
            Episode.deleted_at.is_(None),
        )
        .order_by(EpisodeCharacter.sort_order, EpisodeCharacter.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get(
    session: AsyncSession, user_id: int, character_id: int
) -> EpisodeCharacter:
    """按 id 取角色,JOIN episode→drama 校验归属;越权 / 不存在 → `NotFound`。"""
    stmt = (
        select(EpisodeCharacter)
        .join(Episode, EpisodeCharacter.episode_id == Episode.id)
        .join(Drama, Episode.drama_id == Drama.id)
        .where(
            EpisodeCharacter.id == character_id,
            Drama.user_id == user_id,
            Episode.deleted_at.is_(None),
        )
    )
    character: EpisodeCharacter | None = (
        await session.execute(stmt)
    ).scalar_one_or_none()
    if character is None:
        raise NotFound("Episode character not found")
    return character


async def create(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    *,
    name: str,
    role_type: str | None = None,
    persona: str | None = None,
    motivation: str | None = None,
    traits: list | None = None,
    appearance_desc: str | None = None,
    sort_order: int = 0,
) -> EpisodeCharacter:
    """新建预置角色(`source='preset'`);归属经 episode 校验。"""
    await episode_repo.get(session, user_id, episode_id)
    character = EpisodeCharacter(
        episode_id=episode_id,
        name=name,
        role_type=role_type,
        persona=persona,
        motivation=motivation,
        traits=traits,
        appearance_desc=appearance_desc,
        sort_order=sort_order,
        source="preset",
    )
    session.add(character)
    await session.flush()
    await session.refresh(character)
    return character


async def update(
    session: AsyncSession, character: EpisodeCharacter, *, fields: dict[str, Any]
) -> EpisodeCharacter:
    """按字段更新(白名单过滤);调用方已 `get` 校验归属。"""
    for name, value in fields.items():
        if name in _CHARACTER_FIELDS:
            setattr(character, name, value)
    await session.flush()
    return character


async def delete(session: AsyncSession, character: EpisodeCharacter) -> None:
    """删除已加载角色(物理删;分镜出场引用经 shot_characters FK CASCADE 清理)。"""
    await session.delete(character)
    await session.flush()


async def set_image_media(
    session: AsyncSession, character: EpisodeCharacter, media_id: int | None
) -> None:
    """更新角色的当前形象图指针(`image_media_id`;M3 逻辑指针,无 FK)。

    专用方法(不入 `_CHARACTER_FIELDS` 白名单):形象图经 `character_media_service` 专路径改,
    不走通用角色 update。`media_id=None` 表清除指针。调用方已 `get` 校验归属。
    """
    character.image_media_id = media_id
    await session.flush()


async def bulk_create(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    items: list[dict[str, Any]],
    *,
    source: str = "analysis",
) -> list[int]:
    """批量写入拆解产角色(`source='analysis'` 默认);**返回插入行 id 列表**(D13)。

    `items` 为 dict 列表(适配 LLM 产出),未知键被白名单过滤;`sort_order` 缺省按序。
    """
    await episode_repo.get(session, user_id, episode_id)
    objs: list[EpisodeCharacter] = []
    for idx, item in enumerate(items):
        kwargs = {k: v for k, v in item.items() if k in _CHARACTER_FIELDS}
        kwargs.setdefault("sort_order", idx)
        objs.append(
            EpisodeCharacter(episode_id=episode_id, source=source, **kwargs)
        )
    session.add_all(objs)
    await session.flush()  # 回填自增 id
    return [o.id for o in objs]
