"""分镜端点:`/api/episodes/:id/shots`(列表 / 重排)+ `/api/shots/:id`(拆 / 合 / 改)。

无路由前缀(路径跨 `/episodes` 与 `/shots`)。`appearing`(出场角色)读 + 写:`GET` 批量回填、
`PATCH`/`split` 可全量替换。`target_duration` 越界(∉ 3–15s)软标注进 `warnings`,不阻断(D5)。
错误统一抛 `DomainError` 子类(越权 → 404,跨分析合并 → 409 conflict)。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from drama_smith.api.deps import SessionDep, UserDep
from drama_smith.api.schemas import (
    Envelope,
    ErrorResponse,
    ShotAppearRef,
    ShotEditResult,
    ShotMerge,
    ShotPatch,
    ShotPublic,
    ShotSplit,
    ShotsReorder,
)
from drama_smith.db.models import Shot
from drama_smith.services import shot_service

router = APIRouter(tags=["shots"])

_EP_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "剧集 / 分镜不存在或越权访问(not_found)"}
}


def _appear_refs(rows: list[dict[str, Any]]) -> list[ShotAppearRef]:
    return [
        ShotAppearRef(
            episode_character_id=r["episode_character_id"],
            name=r["name"],
            role_in_shot=r["role_in_shot"],
        )
        for r in rows
    ]


def _shot_public(shot: Shot, rows: list[dict[str, Any]]) -> ShotPublic:
    """`Shot` ORM + 出场扁平行 → `ShotPublic`(appearing 非 ORM 列,经 model_copy 回填)。"""
    return ShotPublic.model_validate(shot).model_copy(update={"appearing": _appear_refs(rows)})


def _edit_result(result: shot_service.ShotEditResult) -> ShotEditResult:
    """service 的 `ShotEditResult` TypedDict(shot+appearing+warnings)→ schema。"""
    return ShotEditResult(
        shot=_shot_public(result["shot"], result["appearing"]),
        warnings=result["warnings"],
    )


@router.get(
    "/episodes/{episode_id}/shots",
    summary="列出当前分析的分镜(含出场)",
    response_model=Envelope[list[ShotPublic]],
    responses={**_EP_NOT_FOUND},
)
async def list_shots(
    episode_id: int, user: UserDep, session: SessionDep
) -> Envelope[list[ShotPublic]]:
    pairs = await shot_service.list_shots_with_appearing(session, user.id, episode_id)
    return Envelope(data=[_shot_public(shot, rows) for shot, rows in pairs])


@router.post(
    "/episodes/{episode_id}/shots/reorder",
    summary="重排分镜",
    description=(
        "按 `ordered_ids` 重排 current_analysis 名下分镜(须恰好覆盖其全部镜);warnings 入 meta。"
    ),
    response_model=Envelope[list[ShotPublic]],
    responses={
        **_EP_NOT_FOUND,
        409: {
            "model": ErrorResponse,
            "description": "幂集不符(conflict)/ 无 current(invalid_state)",
        },
    },
)
async def reorder_shots(
    episode_id: int,
    body: ShotsReorder,
    user: UserDep,
    session: SessionDep,
) -> Envelope[list[ShotPublic]]:
    warnings = await shot_service.reorder_shots(
        session, user.id, episode_id, ordered_ids=body.ordered_ids
    )
    pairs = await shot_service.list_shots_with_appearing(session, user.id, episode_id)
    return Envelope(
        data=[_shot_public(shot, rows) for shot, rows in pairs],
        meta={"warnings": warnings},
    )


@router.patch(
    "/shots/{shot_id}",
    summary="改分镜字段(含出场)",
    response_model=Envelope[ShotEditResult],
    responses={**_EP_NOT_FOUND},
)
async def patch_shot(
    shot_id: int, body: ShotPatch, user: UserDep, session: SessionDep
) -> Envelope[ShotEditResult]:
    fields: dict[str, Any] = {
        k: getattr(body, k) for k in body.model_fields_set if k != "appearing"
    }
    result = await shot_service.patch_shot(
        session, user.id, shot_id, fields=fields, appearing=body.appearing
    )
    return Envelope(data=_edit_result(result))


@router.post(
    "/shots/{shot_id}/split",
    summary="在某镜后插入新镜",
    response_model=Envelope[ShotEditResult],
    responses={**_EP_NOT_FOUND},
)
async def split_shot(
    shot_id: int, body: ShotSplit, user: UserDep, session: SessionDep
) -> Envelope[ShotEditResult]:
    fields: dict[str, Any] = {
        k: getattr(body, k) for k in body.model_fields_set if k != "appearing"
    }
    result = await shot_service.split_shot(
        session, user.id, shot_id, fields=fields, appearing=body.appearing
    )
    return Envelope(data=_edit_result(result))


@router.post(
    "/shots/{shot_id}/merge",
    summary="合并相邻两镜",
    response_model=Envelope[ShotEditResult],
    responses={
        **_EP_NOT_FOUND,
        409: {"model": ErrorResponse, "description": "跨分析合并(conflict)"},
    },
)
async def merge_shots(
    shot_id: int, body: ShotMerge, user: UserDep, session: SessionDep
) -> Envelope[ShotEditResult]:
    result = await shot_service.merge_shots(
        session, user.id, shot_id, into_shot_id=body.into_shot_id
    )
    return Envelope(data=_edit_result(result))
