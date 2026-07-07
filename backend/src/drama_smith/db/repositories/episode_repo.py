"""剧集仓储(归属经 `drama → user`,D1)。

事务边界在 services 层(M0 D14);`user_id` 经 JOIN `dramas` 强制过滤(M0 D6 隔离)。
软删(`deleted_at`);越权 / 不存在 / 已删 → `NotFound`。`list_by_drama` / `create`
先验 drama 归属,避免给他人剧建剧集。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import NotFound
from drama_smith.db.base import utcnow
from drama_smith.db.models import Drama, Episode

# 「未提供」哨兵:与显式 `None`(清空 style_preset)区分,PUT 缺省字段时跳过。
_UNSET: Any = object()


async def _require_drama(session: AsyncSession, user_id: int, drama_id: int) -> Drama:
    """验 drama 归属(供 list_by_drama / create 复用);越权 / 已删 → `NotFound`。"""
    stmt = select(Drama).where(
        Drama.id == drama_id,
        Drama.user_id == user_id,
        Drama.deleted_at.is_(None),
    )
    drama: Drama | None = (await session.execute(stmt)).scalar_one_or_none()
    if drama is None:
        raise NotFound("Drama not found")
    return drama


async def get(session: AsyncSession, user_id: int, episode_id: int) -> Episode:
    """按 id 取剧集,JOIN `dramas` 校验归属链(D1);越权 / 已删 → `NotFound`。"""
    stmt = (
        select(Episode)
        .join(Drama, Episode.drama_id == Drama.id)
        .where(
            Episode.id == episode_id,
            Drama.user_id == user_id,
            Episode.deleted_at.is_(None),
        )
    )
    episode: Episode | None = (await session.execute(stmt)).scalar_one_or_none()
    if episode is None:
        raise NotFound("Episode not found")
    return episode


async def list_by_drama(
    session: AsyncSession, user_id: int, drama_id: int
) -> list[Episode]:
    """列某剧下剧集(先验 drama 归属);排除软删,按 `sort_order`、`id` 排序。"""
    await _require_drama(session, user_id, drama_id)
    stmt = (
        select(Episode)
        .join(Drama, Episode.drama_id == Drama.id)
        .where(
            Episode.drama_id == drama_id,
            Drama.user_id == user_id,
            Episode.deleted_at.is_(None),
        )
        .order_by(Episode.sort_order, Episode.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def create(
    session: AsyncSession,
    user_id: int,
    drama_id: int,
    *,
    title: str,
    aspect_ratio: str,
    style_preset: str | None = None,
    sort_order: int = 0,
) -> Episode:
    """新建剧集(先验 drama 归属);画幅整集统一(FR-A7/A8)。"""
    await _require_drama(session, user_id, drama_id)
    episode = Episode(
        drama_id=drama_id,
        title=title,
        aspect_ratio=aspect_ratio,
        style_preset=style_preset,
        sort_order=sort_order,
    )
    session.add(episode)
    await session.flush()
    await session.refresh(episode)
    return episode


async def update(
    session: AsyncSession,
    episode: Episode,
    *,
    title: str | None = _UNSET,
    aspect_ratio: str | None = _UNSET,
    style_preset: str | None = _UNSET,
    status: str | None = _UNSET,
    sort_order: int | None = _UNSET,
) -> Episode:
    """按字段更新;`_UNSET` 不改动,显式 `None` 清空 `style_preset`。"""
    provided: dict[str, Any] = {
        "title": title,
        "aspect_ratio": aspect_ratio,
        "style_preset": style_preset,
        "status": status,
        "sort_order": sort_order,
    }
    for name, value in provided.items():
        if value is not _UNSET:
            setattr(episode, name, value)
    await session.flush()
    return episode


async def soft_delete(session: AsyncSession, episode: Episode) -> None:
    """软删剧集(子资源 script/analysis/shot 等经 episode 归属链自然隐藏)。"""
    episode.deleted_at = utcnow()
    await session.flush()
