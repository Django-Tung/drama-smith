"""`script_service` 测试:版本指针(append-only / accept / reject)+ difflib 段落 diff(D12)
+ optimize copy-edit 端到端(产新版本、不移指针、返回 diff)。"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.llm.fakes import FakeTextModel

from drama_smith.core.config import get_mek
from drama_smith.core.errors import ModelNotConfigured
from drama_smith.db.base import get_session_factory
from drama_smith.db.repositories import task_repo, user_repo
from drama_smith.services import (
    drama_service,
    episode_service,
    model_config_service,
)
from drama_smith.services import (
    script_service as svc,
)
from drama_smith.tasks import TaskExecutor

_MEK = get_mek()


async def _make_user(s: AsyncSession, username: str = "alice") -> int:
    return (await user_repo.create(s, username=username, password_hash="hash")).id


async def _seed_episode(s: AsyncSession, uid: int) -> int:
    did = (await drama_service.create_drama(s, uid, name="d")).id
    return (await episode_service.create_episode(s, uid, did, title="e", aspect_ratio="16:9")).id


# ---- diff_versions(D12 段落级 diff,按格式分派)----


def _types(diff: list[dict[str, Any]]) -> list[str]:
    return [d["change_type"] for d in diff]


class TestDiffPlain:
    def test_added(self) -> None:
        diff = svc.diff_versions("A\n\nB\n\nC", "A\n\nB\n\nC\n\nD", format="plain")
        assert _types(diff) == ["unchanged", "unchanged", "unchanged", "added"]
        assert diff[-1] == {"seg": 4, "before": "", "after": "D", "change_type": "added"}

    def test_removed(self) -> None:
        diff = svc.diff_versions("A\n\nB\n\nC", "A\n\nC", format="plain")
        assert _types(diff) == ["unchanged", "removed", "unchanged"]

    def test_modified(self) -> None:
        diff = svc.diff_versions("A\n\nB\n\nC", "A\n\nB2\n\nC", format="plain")
        assert _types(diff) == ["unchanged", "modified", "unchanged"]
        assert diff[1] == {"seg": 2, "before": "B", "after": "B2", "change_type": "modified"}

    def test_seg_is_one_based_continuous(self) -> None:
        diff = svc.diff_versions("A\n\nB", "A\n\nB", format="plain")
        assert [d["seg"] for d in diff] == [1, 2]


class TestDiffMarkdown:
    def test_heading_segmentation(self) -> None:
        before = "# 标题一\n正文一\n\n# 标题二\n正文二"
        after = "# 标题一\n正文一改\n\n# 标题三\n正文三"
        diff = svc.diff_versions(before, after, format="markdown")
        # 两节各自 replace → 两段 modified(标题/正文成节,不拆标题与正文)
        assert _types(diff) == ["modified", "modified"]
        assert "正文一改" in diff[0]["after"]
        assert "标题三" in diff[1]["after"]


class TestDiffFountain:
    def test_scene_head_segmentation(self) -> None:
        before = "INT. 咖啡馆 - 日\n小明进门。\n\nEXT. 街道 - 夜\n阿珍离开。"
        after = "INT. 咖啡馆 - 日\n小明进门。"
        diff = svc.diff_versions(before, after, format="fountain")
        assert _types(diff) == ["unchanged", "removed"]
        assert diff[1]["before"].startswith("EXT.")


# ---- 版本指针 ----


class TestVersioning:
    async def test_upsert_creates_input_version_and_moves_current(
        self, db_session: AsyncSession
    ) -> None:
        uid = await _make_user(db_session)
        ep_id = await _seed_episode(db_session, uid)
        v = await svc.upsert_script(db_session, uid, ep_id, content="c1", format="markdown")
        assert v.source == "input"
        script = await svc.get_script(db_session, uid, ep_id)
        assert script.current_version_id == v.id

    async def test_upsert_twice_appends_and_points_to_latest(
        self, db_session: AsyncSession
    ) -> None:
        uid = await _make_user(db_session)
        ep_id = await _seed_episode(db_session, uid)
        v1 = await svc.upsert_script(db_session, uid, ep_id, content="c1")
        v2 = await svc.upsert_script(db_session, uid, ep_id, content="c2")
        versions = await svc.list_versions(db_session, uid, ep_id)
        assert {v.id for v in versions} == {v1.id, v2.id}
        assert (await svc.get_script(db_session, uid, ep_id)).current_version_id == v2.id

    async def test_select_version_moves_pointer(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep_id = await _seed_episode(db_session, uid)
        v1 = await svc.upsert_script(db_session, uid, ep_id, content="c1")
        await svc.upsert_script(db_session, uid, ep_id, content="c2")
        # 回退到 v1(accept = revert)
        await svc.select_version(db_session, uid, ep_id, v1.id)
        assert (await svc.get_script(db_session, uid, ep_id)).current_version_id == v1.id

    async def test_reject_version_keeps_pointer(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep_id = await _seed_episode(db_session, uid)
        v1 = await svc.upsert_script(db_session, uid, ep_id, content="c1")
        latest = await svc.upsert_script(db_session, uid, ep_id, content="c2")
        # reject v1 → 指针不动(仍指 latest),版本保留
        await svc.reject_version(db_session, uid, ep_id, v1.id)
        assert (await svc.get_script(db_session, uid, ep_id)).current_version_id == latest.id
        assert len(await svc.list_versions(db_session, uid, ep_id)) == 2


# ---- optimize_script(copy-edit 异步任务)----


async def _make_text_config(s: AsyncSession, uid: int) -> Any:
    return await model_config_service.create_config(
        s,
        uid,
        purpose="text",
        provider="deepseek",
        model="deepseek-ai/DeepSeek-V3.2",
        api_key="sk-fake-1234567890ABCDEF",
        mek=_MEK,
        base_url="https://api.siliconflow.cn/v1",
    )


class TestOptimize:
    async def test_optimize_produces_version_without_moving_pointer(
        self, db_session: AsyncSession
    ) -> None:
        uid = await _make_user(db_session)
        await _make_text_config(db_session, uid)
        ep_id = await _seed_episode(db_session, uid)
        await svc.upsert_script(db_session, uid, ep_id, content="原文。", format="markdown")
        before_current = (await svc.get_script(db_session, uid, ep_id)).current_version_id

        ex = TaskExecutor(get_session_factory(), 2, 4)
        task = await svc.optimize_script(
            db_session,
            uid,
            ep_id,
            executor=ex,
            mek=_MEK,
            model_factory=lambda _s, _k: FakeTextModel(output='{"content":"润色后正文。"}'),
        )
        await ex._tasks[task.id]

        async with get_session_factory()() as s:
            t = await task_repo.get(s, uid, task.id)
            assert t.status == "succeeded"
            assert t.output_refs is not None and "diff" in t.output_refs
            new_v_id = t.output_refs["version_id"]
            new_v = await svc.get_version(s, uid, new_v_id)
            assert new_v.source == "optimize"
            assert new_v.content == "润色后正文。"
            # 不移 current 指针(accept 是后续 select_version)
            script = await svc.get_script(s, uid, ep_id)
            assert script.current_version_id == before_current
            # diff 含润色后差异
            assert t.output_refs["diff"]

    async def test_optimize_no_config_raises(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep_id = await _seed_episode(db_session, uid)
        await svc.upsert_script(db_session, uid, ep_id, content="原文。", format="markdown")
        with pytest.raises(ModelNotConfigured):
            await svc.optimize_script(
                db_session,
                uid,
                ep_id,
                executor=TaskExecutor(get_session_factory(), 2, 4),
                mek=_MEK,
            )
