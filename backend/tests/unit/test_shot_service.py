"""`shot_service` 测试:拆 / 合 / 排序 + 越界标注 + 无 current analysis 的边界(D5/D11)。"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import InvalidState
from drama_smith.db.repositories import (
    analysis_repo,
    episode_repo,
    shot_repo,
    user_repo,
)
from drama_smith.services import (
    drama_service,
    episode_service,
    script_service,
)
from drama_smith.services import (
    shot_service as svc,
)


async def _make_user(s: AsyncSession, username: str = "alice") -> int:
    return (await user_repo.create(s, username=username, password_hash="hash")).id


async def _seed_episode_with_analysis(
    s: AsyncSession, uid: int, *, n_shots: int = 3
) -> tuple[int, int]:
    """建 drama → episode → 剧本 → analysis(置 current)+ n 个分镜。

    返回 (episode_id, analysis_id)。
    """
    did = (await drama_service.create_drama(s, uid, name="d")).id
    ep_id = (await episode_service.create_episode(s, uid, did, title="e", aspect_ratio="16:9")).id
    await script_service.upsert_script(s, uid, ep_id, content="剧本。", format="markdown")
    sv_id = (await script_service.get_script(s, uid, ep_id)).current_version_id
    assert sv_id is not None
    analysis = await analysis_repo.create(s, uid, ep_id, script_version_id=sv_id)
    await analysis_repo.update_result(s, analysis, status="succeeded", result={})
    episode = await episode_repo.get(s, uid, ep_id)
    await analysis_repo.set_current(s, episode, analysis.id)
    if n_shots:
        await shot_repo.bulk_create(
            s,
            analysis.id,
            ep_id,
            [{"description": f"镜{i}", "target_duration": 5.0} for i in range(1, n_shots + 1)],
        )
    await s.commit()
    return ep_id, analysis.id


class TestListShots:
    async def test_empty_when_no_current_analysis(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        did = (await drama_service.create_drama(db_session, uid, name="d")).id
        ep_id = (
            await episode_service.create_episode(
                db_session, uid, did, title="e", aspect_ratio="16:9"
            )
        ).id
        assert await svc.list_shots(db_session, uid, ep_id) == []

    async def test_lists_current_analysis_shots(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep_id, _ = await _seed_episode_with_analysis(db_session, uid)
        shots = await svc.list_shots(db_session, uid, ep_id)
        assert [s.seq for s in shots] == [1, 2, 3]


class TestPatch:
    async def test_patch_returns_warnings_on_out_of_range(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep_id, _ = await _seed_episode_with_analysis(db_session, uid)
        shots = await svc.list_shots(db_session, uid, ep_id)
        # 太短(<3s)
        r = await svc.patch_shot(db_session, uid, shots[0].id, fields={"target_duration": 1.0})
        assert r["shot"].target_duration == 1.0
        assert len(r["warnings"]) == 1
        assert r["warnings"][0]["issue"] == "too_short"
        # 正常(3–15s)→ 无 warning
        r = await svc.patch_shot(db_session, uid, shots[1].id, fields={"target_duration": 8.0})
        assert r["warnings"] == []


class TestSplitMerge:
    async def test_split_inserts_and_renumbers(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep_id, _ = await _seed_episode_with_analysis(db_session, uid)
        shots = await svc.list_shots(db_session, uid, ep_id)
        new = await svc.split_shot(db_session, uid, shots[0].id, fields={"description": "新镜"})
        after = await svc.list_shots(db_session, uid, ep_id)
        assert len(after) == 4
        assert [s.seq for s in after] == [1, 2, 3, 4]  # dense-rank 无空洞
        assert new["shot"].description == "新镜"

    async def test_merge_combines_adjacent(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep_id, _ = await _seed_episode_with_analysis(db_session, uid)
        shots = await svc.list_shots(db_session, uid, ep_id)
        r = await svc.merge_shots(db_session, uid, shots[0].id, into_shot_id=shots[1].id)
        after = await svc.list_shots(db_session, uid, ep_id)
        assert len(after) == 2
        assert [s.seq for s in after] == [1, 2]
        # 描述拼接
        assert "镜1" in r["shot"].description and "镜2" in r["shot"].description


class TestReorder:
    async def test_reorder_dense_no_gaps(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep_id, _ = await _seed_episode_with_analysis(db_session, uid)
        shots = await svc.list_shots(db_session, uid, ep_id)
        # 倒序重排
        ordered = [s.id for s in reversed(shots)]
        warnings = await svc.reorder_shots(db_session, uid, ep_id, ordered_ids=ordered)
        after = await svc.list_shots(db_session, uid, ep_id)
        assert [s.id for s in after] == ordered
        assert [s.seq for s in after] == [1, 2, 3]
        assert warnings == []  # 全部 5.0s 在区间内 → 无越界标注

    async def test_reorder_no_current_analysis_raises(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        did = (await drama_service.create_drama(db_session, uid, name="d")).id
        ep_id = (
            await episode_service.create_episode(
                db_session, uid, did, title="e", aspect_ratio="16:9"
            )
        ).id
        with pytest.raises(InvalidState):
            await svc.reorder_shots(db_session, uid, ep_id, ordered_ids=[1, 2])
