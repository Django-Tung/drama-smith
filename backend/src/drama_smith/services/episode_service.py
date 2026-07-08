"""剧集用例编排(CRUD,事务边界在此,D1/D14)。

归属经 `episode → drama → user`(D1);跨用户 / 越权 / 已删 → `NotFound`。建剧集时画幅
整集统一(FR-A7/A8)。`update` 复用 repo `_UNSET` 哨兵:`_UNSET` 不改动、显式 `None` 清空
可空字段(`style_preset`)。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.db.models import Episode
from drama_smith.db.repositories import episode_repo
from drama_smith.db.repositories.episode_repo import _UNSET


async def list_episodes(session: AsyncSession, user_id: int, drama_id: int) -> list[Episode]:
    """列某剧的剧集(先验 drama 归属;排除软删,按 `sort_order`、`id`)。"""
    return await episode_repo.list_by_drama(session, user_id, drama_id)


async def get_episode(session: AsyncSession, user_id: int, episode_id: int) -> Episode:
    """取单剧集(归属经 episode→drama→user;越权 → `NotFound`)。"""
    return await episode_repo.get(session, user_id, episode_id)


async def create_episode(
    session: AsyncSession,
    user_id: int,
    drama_id: int,
    *,
    title: str,
    aspect_ratio: str,
    style_preset: str | None = None,
) -> Episode:
    """建剧集(画幅必填,整集统一;先验 drama 归属)。"""
    episode = await episode_repo.create(
        session,
        user_id,
        drama_id,
        title=title,
        aspect_ratio=aspect_ratio,
        style_preset=style_preset,
    )
    await session.commit()
    return episode


async def update_episode(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    *,
    title: object = _UNSET,
    aspect_ratio: object = _UNSET,
    style_preset: object = _UNSET,
    status: object = _UNSET,
) -> Episode:
    """更新剧集;`_UNSET` 不改动、显式 `None` 清空 `style_preset`。归属经 `get` 校验。"""
    episode = await episode_repo.get(session, user_id, episode_id)
    updated = await episode_repo.update(
        session,
        episode,
        title=title,  # type: ignore[arg-type]
        aspect_ratio=aspect_ratio,  # type: ignore[arg-type]
        style_preset=style_preset,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
    )
    await session.commit()
    return updated


async def delete_episode(session: AsyncSession, user_id: int, episode_id: int) -> None:
    """软删剧集(子资源经归属链自然隐藏;归属经 `get` 校验)。"""
    episode = await episode_repo.get(session, user_id, episode_id)
    await episode_repo.soft_delete(session, episode)
    await session.commit()
