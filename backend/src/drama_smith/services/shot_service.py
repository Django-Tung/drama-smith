"""分镜用例编排(拆 / 合 / 排序 + 越界标注,`design.md` D5)。

事务边界在此(D14)。分镜**就地编辑**(无版本表,见 Non-Goals)。`target_duration` 3–15s
仅软校验:越界**不阻断保存**,在响应 `warnings` 里标注(待人工确认,对齐 §5.1);`seq`
重排由 repo 在单事务内 dense-rank 保证无空洞。归属经 analysis→episode→drama。
"""

from __future__ import annotations

from typing import Any, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import InvalidState
from drama_smith.db.models import Shot
from drama_smith.db.repositories import analysis_repo, shot_repo

_MIN_DURATION = 3.0
_MAX_DURATION = 15.0


class ShotEditResult(TypedDict):
    """patch / split / merge 的返回:操作后的镜 + 该镜的越界标注(若有)。"""

    shot: Shot
    warnings: list[dict[str, Any]]


def _duration_warnings(shots: list[Shot]) -> list[dict[str, Any]]:
    """`target_duration` 越出 3–15s 的镜 → warnings(`too_short` / `too_long`);不阻断(D5)。"""
    warnings: list[dict[str, Any]] = []
    for s in shots:
        if s.target_duration is None:
            continue
        if s.target_duration < _MIN_DURATION:
            issue = "too_short"
        elif s.target_duration > _MAX_DURATION:
            issue = "too_long"
        else:
            continue
        warnings.append(
            {"shot_id": s.id, "target_duration": float(s.target_duration), "issue": issue}
        )
    return warnings


async def list_shots(session: AsyncSession, user_id: int, episode_id: int) -> list[Shot]:
    """列 `current_analysis` 名下的分镜(D11);无 current analysis → 空列表。"""
    current = await analysis_repo.get_current(session, user_id, episode_id)
    if current is None:
        return []
    return await shot_repo.list_by_analysis(session, user_id, current.id)


async def patch_shot(
    session: AsyncSession, user_id: int, shot_id: int, *, fields: dict[str, Any]
) -> ShotEditResult:
    """改字段(白名单过滤);返回改后镜 + 越界标注。"""
    shot = await shot_repo.patch(session, user_id, shot_id, fields=fields)
    await session.commit()
    return {"shot": shot, "warnings": _duration_warnings([shot])}


async def split_shot(
    session: AsyncSession, user_id: int, shot_id: int, *, fields: dict[str, Any]
) -> ShotEditResult:
    """在某镜后插入新镜 + 全 analysis 重排;返回新镜 + 越界标注。"""
    new_shot = await shot_repo.split(session, user_id, shot_id, fields=fields)
    await session.commit()
    return {"shot": new_shot, "warnings": _duration_warnings([new_shot])}


async def merge_shots(
    session: AsyncSession, user_id: int, shot_id: int, *, into_shot_id: int
) -> ShotEditResult:
    """合并相邻两镜(删其一、重排);返回合并后镜 + 越界标注。"""
    merged = await shot_repo.merge(session, user_id, shot_id, into_shot_id=into_shot_id)
    await session.commit()
    return {"shot": merged, "warnings": _duration_warnings([merged])}


async def reorder_shots(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    *,
    ordered_ids: list[int],
) -> list[dict[str, Any]]:
    """重排 current_analysis 名下分镜(须恰好覆盖其全部镜);返回重排后的越界标注。

    无 current analysis → `InvalidState`(无分镜可排)。
    """
    current = await analysis_repo.get_current(session, user_id, episode_id)
    if current is None:
        raise InvalidState(
            "Episode has no current analysis to reorder",
            details={"reason": "no_current_analysis"},
        )
    await shot_repo.reorder(session, user_id, current.id, ordered_ids=ordered_ids)
    await session.commit()
    shots = await shot_repo.list_by_analysis(session, user_id, current.id)
    return _duration_warnings(shots)
