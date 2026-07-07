"""分析产物仓储(append-only + `current_analysis_id` 逻辑指针,D11)。

事务边界在 services 层(M0 D14);归属经 `episode → drama → user`,越权 → `NotFound`。
每次拆解追加新 analysis 行(记 `script_version_id`,D11),`episodes.current_analysis_id`
为指向当前生效分析的**逻辑指针**(不加物理 FK,见模型注释);`has_inflight` 支撑 D3 串行约束。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import NotFound
from drama_smith.db.models import Analysis, Drama, Episode
from drama_smith.db.repositories import episode_repo

_UNSET: Any = object()

# D3 串行约束:同一剧集同时至多一个拆解在途。
_INFLIGHT_STATUSES = ("pending", "running")


async def create(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    *,
    script_version_id: int,
    config_snapshot: dict | None = None,
) -> Analysis:
    """新建分析行(`status='pending'`,记发起时所基于的剧本版本 D11)。"""
    await episode_repo.get(session, user_id, episode_id)
    analysis = Analysis(
        episode_id=episode_id,
        status="pending",
        script_version_id=script_version_id,
        config_snapshot=config_snapshot,
    )
    session.add(analysis)
    await session.flush()
    await session.refresh(analysis)
    return analysis


async def update_result(
    session: AsyncSession,
    analysis: Analysis,
    *,
    status: str,
    result: dict | None = _UNSET,
    config_snapshot: dict | None = _UNSET,
) -> Analysis:
    """更新分析状态 / 结果;`_UNSET` 不改动,显式 `None` 清空可空字段。"""
    analysis.status = status
    if result is not _UNSET:
        analysis.result = result
    if config_snapshot is not _UNSET:
        analysis.config_snapshot = config_snapshot
    await session.flush()
    return analysis


async def get(
    session: AsyncSession, user_id: int, analysis_id: int
) -> Analysis:
    """按 id 取分析,JOIN episode→drama 校验归属;越权 → `NotFound`。"""
    stmt = (
        select(Analysis)
        .join(Episode, Analysis.episode_id == Episode.id)
        .join(Drama, Episode.drama_id == Drama.id)
        .where(
            Analysis.id == analysis_id,
            Drama.user_id == user_id,
            Episode.deleted_at.is_(None),
        )
    )
    analysis: Analysis | None = (
        await session.execute(stmt)
    ).scalar_one_or_none()
    if analysis is None:
        raise NotFound("Analysis not found")
    return analysis


async def get_current(
    session: AsyncSession, user_id: int, episode_id: int
) -> Analysis | None:
    """读 `episodes.current_analysis_id` 指针指向的当前分析;无指针 / 未拆解 → `None`。"""
    episode = await episode_repo.get(session, user_id, episode_id)
    if episode.current_analysis_id is None:
        return None
    stmt = select(Analysis).where(
        Analysis.id == episode.current_analysis_id,
        Analysis.episode_id == episode_id,  # 指针必属本剧集(由 set_current 保证)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def set_current(
    session: AsyncSession, episode: Episode, analysis_id: int
) -> None:
    """移当前分析指针(切换 current);analysis 须属该 episode,否则 `NotFound`。"""
    owned = (
        await session.execute(
            select(Analysis.id).where(
                Analysis.id == analysis_id,
                Analysis.episode_id == episode.id,
            )
        )
    ).scalar_one_or_none()
    if owned is None:
        raise NotFound("Analysis not found")
    episode.current_analysis_id = analysis_id
    await session.flush()


async def list_history(
    session: AsyncSession, user_id: int, episode_id: int
) -> list[Analysis]:
    """列某剧集全部分析(新→旧);归属经 episode→drama 校验。"""
    await episode_repo.get(session, user_id, episode_id)
    stmt = (
        select(Analysis)
        .join(Episode, Analysis.episode_id == Episode.id)
        .join(Drama, Episode.drama_id == Drama.id)
        .where(
            Analysis.episode_id == episode_id,
            Drama.user_id == user_id,
            Episode.deleted_at.is_(None),
        )
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def has_inflight(
    session: AsyncSession, user_id: int, episode_id: int
) -> bool:
    """该剧集是否存在在途分析(`pending`/`running`);D3 串行约束判定。"""
    subq = (
        select(Analysis.id)
        .join(Episode, Analysis.episode_id == Episode.id)
        .join(Drama, Episode.drama_id == Drama.id)
        .where(
            Analysis.episode_id == episode_id,
            Drama.user_id == user_id,
            Episode.deleted_at.is_(None),
            Analysis.status.in_(_INFLIGHT_STATUSES),
        )
    )
    stmt = select(exists(subq))
    return bool((await session.execute(stmt)).scalar())
