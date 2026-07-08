"""分镜仓储(逐镜行,可拆/合/排序,D5)。

事务边界在 services 层(M0 D14);归属经 `analysis → episode → drama → user`,越权 → `NotFound`。
拆 / 合 / 重排在事务内对**单 analysis** 的镜做 dense-rank 重排,保证 `seq` 1..N 无空洞(D5)。
`list_by_analysis` 为主查询路径(GET /shots 由 service 解析 `current_analysis_id` 后调用)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import Conflict, NotFound
from drama_smith.db.models import Analysis, Drama, Episode, EpisodeCharacter, Shot, ShotCharacter

# 分镜可设字段(patch / split / bulk_create 白名单过滤)。
_SHOT_FIELDS = {
    "description",
    "shot_type",
    "scene",
    "plot_point",
    "dialogue",
    "target_duration",
    "camera_move",
    "related_plotline",
    "related_conflict",
}


def _renumber(shots: list[Shot]) -> None:
    """dense-rank:按列表顺序赋 `seq` = 1..N(D5,无空洞)。"""
    for seq, shot in enumerate(shots, start=1):
        shot.seq = seq


async def list_by_analysis(
    session: AsyncSession, user_id: int, analysis_id: int
) -> list[Shot]:
    """列某分析的全部分镜(归属经 analysis→episode→drama 校验);按 `seq`、`id`。"""
    stmt = (
        select(Shot)
        .join(Analysis, Shot.analysis_id == Analysis.id)
        .join(Episode, Shot.episode_id == Episode.id)
        .join(Drama, Episode.drama_id == Drama.id)
        .where(
            Shot.analysis_id == analysis_id,
            Drama.user_id == user_id,
            Episode.deleted_at.is_(None),
        )
        .order_by(Shot.seq, Shot.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_by_episode(
    session: AsyncSession, user_id: int, episode_id: int
) -> list[Shot]:
    """列某剧集全部分镜(跨分析,按 analysis_id、seq);归属经 episode→drama 校验。"""
    stmt = (
        select(Shot)
        .join(Episode, Shot.episode_id == Episode.id)
        .join(Drama, Episode.drama_id == Drama.id)
        .where(
            Shot.episode_id == episode_id,
            Drama.user_id == user_id,
            Episode.deleted_at.is_(None),
        )
        .order_by(Shot.analysis_id, Shot.seq, Shot.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get(session: AsyncSession, user_id: int, shot_id: int) -> Shot:
    """按 id 取分镜,JOIN episode→drama 校验归属;越权 → `NotFound`。"""
    stmt = (
        select(Shot)
        .join(Episode, Shot.episode_id == Episode.id)
        .join(Drama, Episode.drama_id == Drama.id)
        .where(
            Shot.id == shot_id,
            Drama.user_id == user_id,
            Episode.deleted_at.is_(None),
        )
    )
    shot: Shot | None = (await session.execute(stmt)).scalar_one_or_none()
    if shot is None:
        raise NotFound("Shot not found")
    return shot


async def bulk_create(
    session: AsyncSession,
    analysis_id: int,
    episode_id: int,
    items: list[dict[str, Any]],
) -> list[Shot]:
    """拆解产出批量写分镜;`seq` 按序 1..N。`items` 未知键被白名单过滤。"""
    objs: list[Shot] = []
    for seq, item in enumerate(items, start=1):
        kwargs = {k: v for k, v in item.items() if k in _SHOT_FIELDS}
        objs.append(
            Shot(
                analysis_id=analysis_id,
                episode_id=episode_id,
                seq=seq,
                **kwargs,
            )
        )
    session.add_all(objs)
    await session.flush()
    return objs


async def patch(
    session: AsyncSession, user_id: int, shot_id: int, *, fields: dict[str, Any]
) -> Shot:
    """按字段更新分镜(白名单过滤);归属经 `get` 校验。"""
    shot = await get(session, user_id, shot_id)
    for name, value in fields.items():
        if name in _SHOT_FIELDS:
            setattr(shot, name, value)
    await session.flush()
    return shot


async def split(
    session: AsyncSession, user_id: int, shot_id: int, *, fields: dict[str, Any]
) -> Shot:
    """在某镜之后插入新镜,事务内对该 analysis 全部镜 dense-rank 重排(D5)。"""
    shot = await get(session, user_id, shot_id)
    shots = await list_by_analysis(session, user_id, shot.analysis_id)
    idx = next(i for i, s in enumerate(shots) if s.id == shot.id)
    new_shot = Shot(analysis_id=shot.analysis_id, episode_id=shot.episode_id)
    for name, value in fields.items():
        if name in _SHOT_FIELDS:
            setattr(new_shot, name, value)
    shots.insert(idx + 1, new_shot)
    session.add(new_shot)
    _renumber(shots)
    await session.flush()
    await session.refresh(new_shot)
    return new_shot


async def merge(
    session: AsyncSession, user_id: int, shot_id: int, *, into_shot_id: int
) -> Shot:
    """合并 `shot_id` 到 `into_shot_id`(须同 analysis);描述拼接,删被合并镜,重排。"""
    shot = await get(session, user_id, shot_id)
    into = await get(session, user_id, into_shot_id)
    if shot.analysis_id != into.analysis_id:
        raise Conflict("Cannot merge shots from different analyses")
    shots = await list_by_analysis(session, user_id, into.analysis_id)
    merged = "\n".join(s for s in (into.description, shot.description) if s)
    into.description = merged
    shots = [s for s in shots if s.id != shot.id]
    _renumber(shots)
    await session.delete(shot)
    await session.flush()
    return into


async def reorder(
    session: AsyncSession,
    user_id: int,
    analysis_id: int,
    *,
    ordered_ids: list[int],
) -> None:
    """按 `ordered_ids` 顺序重排 `seq`(须恰好覆盖该 analysis 全部镜,否则 `Conflict`)。"""
    shots = await list_by_analysis(session, user_id, analysis_id)
    by_id = {s.id: s for s in shots}
    if set(by_id) != set(ordered_ids):
        raise Conflict("ordered_ids must cover exactly the analysis shots")
    for seq, sid in enumerate(ordered_ids, start=1):
        by_id[sid].seq = seq
    await session.flush()


async def bulk_link_characters(
    session: AsyncSession,
    links: list[tuple[int, list[int]]],
) -> None:
    """批量写 `shot_characters`(分镜 → 出场角色);`links` = [(shot_id, [char_id, ...]), ...]。

    拆解落库(D13 persist)用:shots 已 `bulk_create` 拿到 id 后,经 name→id 映射解析 appearing,
    再由此方法把关联落库。归属由调用方把关(service 已验 current analysis 归属);`role_in_shot`
    本期不填(随分镜对白演进)。空 `links` 直接返回(无出场角色的镜不产生关联行)。
    """
    if not links:
        return
    objs = [
        ShotCharacter(shot_id=shot_id, episode_character_id=cid)
        for shot_id, char_ids in links
        for cid in char_ids
    ]
    session.add_all(objs)
    await session.flush()


async def list_appearing(
    session: AsyncSession, shot_ids: list[int]
) -> list[dict[str, Any]]:
    """批量取分镜出场角色(扁平行 `[{shot_id, episode_character_id, name, role_in_shot}]`)。

    JOIN `shot_characters` × `episode_characters` 取角色名;按 `shot_id`、角色名排序。归属由
    调用方把关(`shot_ids` 已经所有权校验路径加载,故结果天然限定在该用户的镜)。空列表 → `[]`
    (避免 `IN ()` 在 MySQL 非法)。供 `GET /episodes/:id/shots` 与 patch/split/merge 响应回填。
    """
    if not shot_ids:
        return []
    stmt = (
        select(
            ShotCharacter.shot_id,
            ShotCharacter.episode_character_id,
            EpisodeCharacter.name,
            ShotCharacter.role_in_shot,
        )
        .join(EpisodeCharacter, ShotCharacter.episode_character_id == EpisodeCharacter.id)
        .where(ShotCharacter.shot_id.in_(shot_ids))
        .order_by(ShotCharacter.shot_id, EpisodeCharacter.name)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "shot_id": row.shot_id,
            "episode_character_id": row.episode_character_id,
            "name": row.name,
            "role_in_shot": row.role_in_shot,
        }
        for row in rows
    ]


async def replace_appearing(
    session: AsyncSession,
    shot_id: int,
    episode_id: int,
    character_ids: list[int],
) -> list[int]:
    """全量替换某镜出场角色:先删后插,仅链接**属本 `episode`** 的角色 id(防跨剧集误链)。

    返回实际落库的 `character_id` 列表(去重保序;越权 / 不属本 episode 的 id 静默丢弃)。
    `shot_id` 归属由调用方已验(patch/split 经 `shot_repo.get`);`episode_id` 用作角色归属过滤。
    """
    await session.execute(delete(ShotCharacter).where(ShotCharacter.shot_id == shot_id))
    linked: list[int] = []
    if character_ids:
        unique: list[int] = []
        seen: set[int] = set()
        for cid in character_ids:
            if cid not in seen:
                seen.add(cid)
                unique.append(cid)
        valid = set(
            (
                await session.execute(
                    select(EpisodeCharacter.id).where(
                        EpisodeCharacter.episode_id == episode_id,
                        EpisodeCharacter.id.in_(unique),
                    )
                )
            ).scalars().all()
        )
        linked = [cid for cid in unique if cid in valid]
        if linked:
            await session.execute(
                insert(ShotCharacter),
                [{"shot_id": shot_id, "episode_character_id": cid} for cid in linked],
            )
    await session.flush()
    return linked
