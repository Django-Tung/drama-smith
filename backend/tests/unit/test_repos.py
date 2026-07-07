"""剧目/角色/分析/分镜/任务仓储单测。

覆盖:归属链(D1,经 JOIN drama 校验)、软删排除、`has_inflight`(D3 串行)、
shot 拆/合/重排 dense-rank 无空洞(D5)、`interrupt_running`(D4)、跨用户隔离(`NotFound`)。
直连测试库会话(`db_session` 夹具),不走 HTTP。
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import Conflict, NotFound
from drama_smith.db.repositories import (
    analysis_repo,
    drama_repo,
    episode_character_repo,
    episode_repo,
    script_repo,
    shot_repo,
    task_repo,
    user_repo,
)


async def _make_user(session: AsyncSession, username: str = "alice") -> int:
    return (await user_repo.create(session, username=username, password_hash="hash")).id


async def _make_episode(
    session: AsyncSession, user_id: int, *, title: str = "EP", aspect_ratio: str = "16:9"
):
    drama = await drama_repo.create(session, user_id, name="Drama")
    return await episode_repo.create(
        session, user_id, drama.id, title=title, aspect_ratio=aspect_ratio
    )


async def _make_analysis(session: AsyncSession, user_id: int, episode):
    version = await script_repo.upsert_input_version(
        session, user_id, episode.id, content="剧本正文", format="markdown"
    )
    return await analysis_repo.create(
        session, user_id, episode.id, script_version_id=version.id
    )


class TestDramaRepo:
    async def test_create_list_get(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        d = await drama_repo.create(db_session, uid, name="我的剧")
        assert [x.id for x in await drama_repo.list_dramas(db_session, uid)] == [d.id]
        assert (await drama_repo.get(db_session, uid, d.id)).name == "我的剧"

    async def test_soft_delete_excluded(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        d = await drama_repo.create(db_session, uid, name="待删")
        await drama_repo.soft_delete(db_session, d)
        assert await drama_repo.list_dramas(db_session, uid) == []
        with pytest.raises(NotFound):
            await drama_repo.get(db_session, uid, d.id)

    async def test_rename(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        d = await drama_repo.create(db_session, uid, name="旧名")
        await drama_repo.rename(db_session, d, name="新名")
        await db_session.refresh(d)
        assert d.name == "新名"

    async def test_cross_user_not_found(self, db_session: AsyncSession) -> None:
        ua = await _make_user(db_session, "alice")
        ub = await _make_user(db_session, "bob")
        d = await drama_repo.create(db_session, ua, name="A 的剧")
        with pytest.raises(NotFound):
            await drama_repo.get(db_session, ub, d.id)


class TestEpisodeRepo:
    async def test_create_list_get(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        drama = await drama_repo.create(db_session, uid, name="D")
        ep = await episode_repo.create(
            db_session, uid, drama.id, title="E1", aspect_ratio="9:16"
        )
        listed = await episode_repo.list_by_drama(db_session, uid, drama.id)
        assert [e.id for e in listed] == [ep.id]
        assert (await episode_repo.get(db_session, uid, ep.id)).title == "E1"

    async def test_ownership_chain_cross_user(self, db_session: AsyncSession) -> None:
        # alice 的剧集,bob 经归属链 JOIN 访问 → NotFound(不泄露存在性)
        ua = await _make_user(db_session, "alice")
        ub = await _make_user(db_session, "bob")
        ep = await _make_episode(db_session, ua)
        with pytest.raises(NotFound):
            await episode_repo.get(db_session, ub, ep.id)

    async def test_create_on_others_drama_not_found(
        self, db_session: AsyncSession
    ) -> None:
        ua = await _make_user(db_session, "alice")
        ub = await _make_user(db_session, "bob")
        drama = await drama_repo.create(db_session, ua, name="A 的剧")
        with pytest.raises(NotFound):
            await episode_repo.create(
                db_session, ub, drama.id, title="X", aspect_ratio="16:9"
            )


class TestScriptRepo:
    async def test_upsert_creates_and_increments(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep = await _make_episode(db_session, uid)
        v1 = await script_repo.upsert_input_version(
            db_session, uid, ep.id, content="v1"
        )
        assert v1.version_no == 1
        script = await script_repo.get(db_session, uid, ep.id)
        assert script.current_version_id == v1.id
        v2 = await script_repo.upsert_input_version(
            db_session, uid, ep.id, content="v2"
        )
        assert v2.version_no == 2
        await db_session.refresh(script)
        assert script.current_version_id == v2.id

    async def test_list_versions_newest_first(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep = await _make_episode(db_session, uid)
        await script_repo.upsert_input_version(db_session, uid, ep.id, content="v1")
        await script_repo.upsert_input_version(db_session, uid, ep.id, content="v2")
        versions = await script_repo.list_versions(db_session, uid, ep.id)
        assert [v.version_no for v in versions] == [2, 1]

    async def test_cross_user_get_not_found(self, db_session: AsyncSession) -> None:
        ua = await _make_user(db_session, "alice")
        ub = await _make_user(db_session, "bob")
        ep = await _make_episode(db_session, ua)
        await script_repo.upsert_input_version(db_session, ua, ep.id, content="x")
        with pytest.raises(NotFound):
            await script_repo.get(db_session, ub, ep.id)


class TestEpisodeCharacterRepo:
    async def test_create_and_list(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep = await _make_episode(db_session, uid)
        c = await episode_character_repo.create(
            db_session, uid, ep.id, name="主角", role_type="protagonist"
        )
        assert c.source == "preset"
        chars = await episode_character_repo.list_by_episode(db_session, uid, ep.id)
        assert [x.id for x in chars] == [c.id]

    async def test_bulk_create_returns_ids(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep = await _make_episode(db_session, uid)
        ids = await episode_character_repo.bulk_create(
            db_session,
            uid,
            ep.id,
            [{"name": "甲", "role_type": "lead"}, {"name": "乙"}],
            source="analysis",
        )
        assert len(ids) == 2
        chars = await episode_character_repo.list_by_episode(db_session, uid, ep.id)
        assert {c.name for c in chars} == {"甲", "乙"}
        assert all(c.source == "analysis" for c in chars)

    async def test_cross_user_not_found(self, db_session: AsyncSession) -> None:
        ua = await _make_user(db_session, "alice")
        ub = await _make_user(db_session, "bob")
        ep = await _make_episode(db_session, ua)
        c = await episode_character_repo.create(db_session, ua, ep.id, name="X")
        with pytest.raises(NotFound):
            await episode_character_repo.get(db_session, ub, c.id)


class TestAnalysisRepo:
    async def test_create_current_history(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep = await _make_episode(db_session, uid)
        a = await _make_analysis(db_session, uid, ep)
        assert a.status == "pending"
        # create 不自动 set_current(留待 service succeeded 时移指针)
        assert await analysis_repo.get_current(db_session, uid, ep.id) is None
        await analysis_repo.set_current(db_session, ep, a.id)
        await db_session.refresh(ep)
        current = await analysis_repo.get_current(db_session, uid, ep.id)
        assert current is not None and current.id == a.id
        assert [h.id for h in await analysis_repo.list_history(db_session, uid, ep.id)] == [a.id]

    async def test_has_inflight_lifecycle(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep = await _make_episode(db_session, uid)
        assert await analysis_repo.has_inflight(db_session, uid, ep.id) is False
        a = await _make_analysis(db_session, uid, ep)
        assert await analysis_repo.has_inflight(db_session, uid, ep.id) is True
        await analysis_repo.update_result(
            db_session, a, status="succeeded", result={"characters": []}
        )
        assert await analysis_repo.has_inflight(db_session, uid, ep.id) is False

    async def test_cross_user_not_found(self, db_session: AsyncSession) -> None:
        ua = await _make_user(db_session, "alice")
        ub = await _make_user(db_session, "bob")
        ep = await _make_episode(db_session, ua)
        a = await _make_analysis(db_session, ua, ep)
        with pytest.raises(NotFound):
            await analysis_repo.get(db_session, ub, a.id)


class TestShotRepo:
    async def test_bulk_create_dense_seqs(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep = await _make_episode(db_session, uid)
        a = await _make_analysis(db_session, uid, ep)
        shots = await shot_repo.bulk_create(
            db_session,
            a.id,
            ep.id,
            [{"description": "镜1"}, {"description": "镜2"}, {"description": "镜3"}],
        )
        assert [s.seq for s in shots] == [1, 2, 3]
        listed = await shot_repo.list_by_analysis(db_session, uid, a.id)
        assert [s.seq for s in listed] == [1, 2, 3]

    async def test_split_renumbers_no_gap(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep = await _make_episode(db_session, uid)
        a = await _make_analysis(db_session, uid, ep)
        shots = await shot_repo.bulk_create(
            db_session,
            a.id,
            ep.id,
            [{"description": "镜1"}, {"description": "镜2"}, {"description": "镜3"}],
        )
        new = await shot_repo.split(
            db_session, uid, shots[0].id, fields={"description": "新镜"}
        )
        listed = await shot_repo.list_by_analysis(db_session, uid, a.id)
        assert [s.seq for s in listed] == [1, 2, 3, 4]  # 无空洞
        assert listed[1].id == new.id  # 新镜插入在原镜1 之后(seq=2)

    async def test_merge_renumbers(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep = await _make_episode(db_session, uid)
        a = await _make_analysis(db_session, uid, ep)
        shots = await shot_repo.bulk_create(
            db_session,
            a.id,
            ep.id,
            [{"description": "镜1"}, {"description": "镜2"}, {"description": "镜3"}],
        )
        into = await shot_repo.merge(
            db_session, uid, shots[1].id, into_shot_id=shots[0].id
        )
        listed = await shot_repo.list_by_analysis(db_session, uid, a.id)
        assert [s.seq for s in listed] == [1, 2]  # 3 → 2,无空洞
        assert "镜1" in into.description and "镜2" in into.description

    async def test_reorder(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep = await _make_episode(db_session, uid)
        a = await _make_analysis(db_session, uid, ep)
        shots = await shot_repo.bulk_create(
            db_session,
            a.id,
            ep.id,
            [{"description": "A"}, {"description": "B"}, {"description": "C"}],
        )
        await shot_repo.reorder(
            db_session,
            uid,
            a.id,
            ordered_ids=[shots[2].id, shots[1].id, shots[0].id],
        )
        listed = await shot_repo.list_by_analysis(db_session, uid, a.id)
        assert [s.description for s in listed] == ["C", "B", "A"]
        assert [s.seq for s in listed] == [1, 2, 3]

    async def test_reorder_mismatch_conflict(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep = await _make_episode(db_session, uid)
        a = await _make_analysis(db_session, uid, ep)
        shots = await shot_repo.bulk_create(
            db_session, a.id, ep.id, [{"description": "A"}, {"description": "B"}]
        )
        with pytest.raises(Conflict):
            await shot_repo.reorder(db_session, uid, a.id, ordered_ids=[shots[0].id])

    async def test_cross_user_not_found(self, db_session: AsyncSession) -> None:
        ua = await _make_user(db_session, "alice")
        ub = await _make_user(db_session, "bob")
        ep = await _make_episode(db_session, ua)
        a = await _make_analysis(db_session, ua, ep)
        shots = await shot_repo.bulk_create(db_session, a.id, ep.id, [{"description": "X"}])
        with pytest.raises(NotFound):
            await shot_repo.get(db_session, ub, shots[0].id)


class TestTaskRepo:
    async def test_create_progress_finish(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep = await _make_episode(db_session, uid)
        t = await task_repo.create(db_session, uid, episode_id=ep.id, type="analyze")
        assert t.status == "pending" and t.progress == 0
        await task_repo.start(db_session, uid, t.id)
        await task_repo.update_progress(db_session, uid, t.id, 50, stage="extracting")
        await task_repo.finish(
            db_session, uid, t.id, status="succeeded", output_refs={"analysis_id": 1}
        )
        await db_session.refresh(t)
        assert t.status == "succeeded"
        assert t.progress == 50
        assert t.stage == "extracting"
        assert t.finished_at is not None
        assert t.output_refs == {"analysis_id": 1}

    async def test_cross_user_not_found(self, db_session: AsyncSession) -> None:
        ua = await _make_user(db_session, "alice")
        ub = await _make_user(db_session, "bob")
        t = await task_repo.create(db_session, ua, episode_id=None, type="optimize")
        with pytest.raises(NotFound):
            await task_repo.get(db_session, ub, t.id)

    async def test_interrupt_running(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep = await _make_episode(db_session, uid)
        t = await task_repo.create(db_session, uid, episode_id=ep.id, type="analyze")
        await task_repo.start(db_session, uid, t.id)
        # 模拟进程重启:interrupt_running 把残留 running → interrupted(D4)
        count = await task_repo.interrupt_running(db_session)
        assert count >= 1
        await db_session.refresh(t)
        assert t.status == "interrupted"
        assert t.error is not None and t.error["code"] == "restart_interrupted"
