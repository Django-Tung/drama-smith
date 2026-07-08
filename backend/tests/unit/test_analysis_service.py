"""`analysis_service` 用例测试:analyze 端到端(落库 + current 移动)+ 门禁 / 串行 / 失败兜底。

复用 `test_analysis_graph` 的 `_RoutingTextModel`(按 system 提示路由)驱动 5 节点;失败路径用
`FakeTextModel`。executor 真跑(进程内 asyncio),`await executor._tasks[task.id]` 等其完成后验库。

**会话语义**:work 闭包在**独立事务**里落库,而 `db_session` 仍持有发起时的 identity-map /
事务快照(连 `commit`/`expire_all`/`rollback` 都无法可靠刷新——rollback 反触发 `MissingGreenlet`)。
故验证一律经**全新 session**(`async with get_session_factory()()`)读取其提交,
setup 仍用 `db_session`。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.llm.fakes import FakeTextModel

from drama_smith.core.config import get_mek
from drama_smith.core.errors import (
    InvalidState,
    ModelNotConfigured,
    ProviderAuthFailed,
    ScriptRequired,
)
from drama_smith.db.base import get_session_factory
from drama_smith.db.models import Script, ShotCharacter
from drama_smith.db.repositories import (
    analysis_repo,
    episode_character_repo,
    shot_repo,
    task_repo,
    user_repo,
)
from drama_smith.services import analysis_service as svc
from drama_smith.services import (
    drama_service,
    episode_service,
    model_config_service,
    script_service,
)
from drama_smith.tasks import TaskExecutor

_MEK = get_mek()


class _RoutingTextModel:
    """按 system 提示关键词路由返回对应维度 JSON 的替身(复用 test_analysis_graph 范式)。

    路由顺序有讲究:split_shots 的 system 含「角色」(已知角色清单),须先被「分镜」截走。
    """

    async def chat(self, messages: Sequence[Mapping[str, str]], **params: Any) -> str:
        del params
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        if "分镜" in system:
            return '{"shots":[{"description":"小明进门","appearing":["小明"],"target_duration":5}]}'
        if "情节线" in system:
            return '{"plotlines":[{"name":"主线","type":"主线"}]}'
        if "冲突" in system:
            return '{"conflicts":[{"type":"人vs人","parties":"小明 vs 阿珍"}]}'
        if "节奏" in system:
            return '{"pacing":{"structure":"三幕","climax":"相遇"}}'
        if "角色" in system:
            return '{"characters":[{"name":"小明","role_type":"主角"}]}'
        return "{}"

    async def probe(self) -> None:
        return None


async def _make_user(session: AsyncSession, username: str = "alice") -> int:
    return (await user_repo.create(session, username=username, password_hash="hash")).id


async def _make_text_config(session: AsyncSession, uid: int) -> Any:
    return await model_config_service.create_config(
        session,
        uid,
        purpose="text",
        provider="deepseek",
        model="deepseek-ai/DeepSeek-V3.2",
        api_key="sk-fake-1234567890ABCDEF",
        mek=_MEK,
        base_url="https://api.siliconflow.cn/v1",
    )


async def _seed_episode(
    session: AsyncSession,
    uid: int,
    *,
    content: str = "第一幕:小明走进咖啡馆,遇见阿珍。",
    preset: str | None = None,
) -> int:
    """建 drama → episode → 剧本版本(current 已移);可选预置角色。返回 episode_id。"""
    drama = await drama_service.create_drama(session, uid, name="d")
    episode = await episode_service.create_episode(
        session, uid, drama.id, title="e", aspect_ratio="16:9"
    )
    await script_service.upsert_script(session, uid, episode.id, content=content, format="markdown")
    if preset is not None:
        await episode_character_repo.create(session, uid, episode.id, name=preset)
    return episode.id


def _executor() -> TaskExecutor:
    return TaskExecutor(get_session_factory(), max_per_user=2, max_global=4)


def _factory(model: Any) -> Any:
    """忽略 (snapshot,key) 的接缝替身工厂(镜像 test_model_config_service)。"""
    return lambda _snapshot, _key: model


async def _await_task(ex: TaskExecutor, task_id: int) -> None:
    """等 executor 后台 work 跑完(提交时已存入 `_tasks`)。"""
    await ex._tasks[task_id]


class TestAnalyzeEndToEnd:
    async def test_success_persists_and_moves_current(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        await _make_text_config(db_session, uid)
        ep_id = await _seed_episode(db_session, uid, preset="小明")
        ex = _executor()

        task = await svc.analyze(
            db_session,
            uid,
            ep_id,
            executor=ex,
            mek=_MEK,
            model_factory=_factory(_RoutingTextModel()),
        )
        await _await_task(ex, task.id)

        # work 在独立事务落库 → 用全新 session 验证其提交
        async with get_session_factory()() as s:
            t = await task_repo.get(s, uid, task.id)
            assert t.status == "succeeded"
            current = await analysis_repo.get_current(s, uid, ep_id)
            assert current is not None
            assert current.status == "succeeded"
            assert current.script_version_id is not None
            # 四维 result
            assert current.result is not None
            assert current.result["characters"][0]["name"] == "小明"
            assert current.result["plotlines"][0]["name"] == "主线"
            assert current.result["conflicts"][0]["type"] == "人vs人"
            assert current.result["pacing"]["structure"] == "三幕"
            # shots 落库
            shots = await shot_repo.list_by_analysis(s, uid, current.id)
            assert len(shots) == 1
            assert shots[0].target_duration == 5
            # D13:appearing "小明" 解析为 episode_character_id
            # —— preset 优先(同名 extracted 行也存在)
            chars = await episode_character_repo.list_by_episode(s, uid, ep_id)
            preset = next(c for c in chars if c.source == "preset")
            extracted = [c for c in chars if c.source == "analysis"]
            assert any(c.name == "小明" for c in extracted)
            links = (
                (await s.execute(select(ShotCharacter).where(ShotCharacter.shot_id == shots[0].id)))
                .scalars()
                .all()
            )
            assert len(links) == 1
            assert links[0].episode_character_id == preset.id


class TestAnalyzeGates:
    async def test_no_text_config_raises(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        ep_id = await _seed_episode(db_session, uid)
        with pytest.raises(ModelNotConfigured):
            await svc.analyze(db_session, uid, ep_id, executor=_executor(), mek=_MEK)

    async def test_no_script_raises_script_required(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        await _make_text_config(db_session, uid)
        drama = await drama_service.create_drama(db_session, uid, name="d")
        episode = await episode_service.create_episode(
            db_session, uid, drama.id, title="e", aspect_ratio="16:9"
        )
        # 直接插「空 script 容器」(current_version_id=None,正常流程到不了此态)→ ScriptRequired(422)
        db_session.add(Script(episode_id=episode.id))
        await db_session.commit()
        with pytest.raises(ScriptRequired):
            await svc.analyze(
                db_session,
                uid,
                episode.id,
                executor=_executor(),
                mek=_MEK,
                model_factory=_factory(_RoutingTextModel()),
            )

    async def test_inflight_analysis_blocks_second(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        await _make_text_config(db_session, uid)
        ep_id = await _seed_episode(db_session, uid)
        # 已有一条 pending 分析 → has_inflight 命中 → 串行拒绝
        sv_id = (await script_service.get_script(db_session, uid, ep_id)).current_version_id
        assert sv_id is not None
        await analysis_repo.create(db_session, uid, ep_id, script_version_id=sv_id)
        await db_session.commit()
        with pytest.raises(InvalidState):
            await svc.analyze(
                db_session,
                uid,
                ep_id,
                executor=_executor(),
                mek=_MEK,
                model_factory=_factory(_RoutingTextModel()),
            )


class TestAnalyzeFailures:
    async def test_provider_auth_fail_marks_invalid_and_failed(
        self, db_session: AsyncSession
    ) -> None:
        uid = await _make_user(db_session)
        cfg = await _make_text_config(db_session, uid)
        ep_id = await _seed_episode(db_session, uid)
        ex = _executor()
        task = await svc.analyze(
            db_session,
            uid,
            ep_id,
            executor=ex,
            mek=_MEK,
            model_factory=_factory(FakeTextModel(chat_outcomes=[ProviderAuthFailed("bad key")])),
        )
        await _await_task(ex, task.id)

        async with get_session_factory()() as s:
            assert (await task_repo.get(s, uid, task.id)).status == "failed"
            # D8:鉴权失败置配置 invalid
            assert (await model_config_service.get_config(s, uid, cfg.id)).status == "invalid"
            # 失败未移 current 指针
            assert await analysis_repo.get_current(s, uid, ep_id) is None

    async def test_parse_error_marks_analysis_failed(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        await _make_text_config(db_session, uid)
        ep_id = await _seed_episode(db_session, uid)
        ex = _executor()
        task = await svc.analyze(
            db_session,
            uid,
            ep_id,
            executor=ex,
            mek=_MEK,
            model_factory=_factory(FakeTextModel(output="not-json")),
        )
        await _await_task(ex, task.id)

        async with get_session_factory()() as s:
            assert (await task_repo.get(s, uid, task.id)).status == "failed"
            # 解析失败非鉴权错 → 配置仍 active
            assert (await model_config_service.require_active_text(s, uid)).status == "active"


class TestGetAndSelect:
    async def _run_one(self, db_session: AsyncSession, uid: int, ep_id: int) -> None:
        ex = _executor()
        task = await svc.analyze(
            db_session,
            uid,
            ep_id,
            executor=ex,
            mek=_MEK,
            model_factory=_factory(_RoutingTextModel()),
        )
        await _await_task(ex, task.id)

    async def test_get_analysis_shape_and_stale_flag(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        await _make_text_config(db_session, uid)
        ep_id = await _seed_episode(db_session, uid)
        await self._run_one(db_session, uid, ep_id)

        async with get_session_factory()() as s:
            # 刚拆完:有 current、无在途、stale_flag=False(版本未变)
            info = await svc.get_analysis(s, uid, ep_id)
            assert info["current_analysis"] is not None
            assert info["inflight_task"] is None
            assert info["stale_flag"] is False

            # 改了剧本 → current 所基于版本 ≠ 当前版本 → stale_flag=True(提示重拆,不阻断)
            await script_service.upsert_script(
                s, uid, ep_id, content="第二幕:阿珍离开。", format="markdown"
            )
            info = await svc.get_analysis(s, uid, ep_id)
            assert info["stale_flag"] is True

    async def test_select_current_analysis(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        await _make_text_config(db_session, uid)
        ep_id = await _seed_episode(db_session, uid)
        await self._run_one(db_session, uid, ep_id)

        async with get_session_factory()() as s:
            first = await analysis_repo.get_current(s, uid, ep_id)
            assert first is not None
            # 直接建第二条 succeeded 分析,切换 current 指针到它
            second = await analysis_repo.create(
                s, uid, ep_id, script_version_id=first.script_version_id
            )
            await analysis_repo.update_result(s, second, status="succeeded", result={})
            await s.commit()
            await svc.select_current_analysis(s, uid, ep_id, second.id)

        async with get_session_factory()() as s:
            current = await analysis_repo.get_current(s, uid, ep_id)
            assert current is not None
            assert current.id == second.id
