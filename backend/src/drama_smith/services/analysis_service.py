"""分析用例编排(拆解异步任务 + 结构化落库 + 双语义读,`design.md` D3/D8/D9/D11/D13)。

事务边界:发起路径用请求 session(create task/analysis → commit);work 闭包在执行器后台跑,
开自己的 session(`get_session_factory()`)。落库(D13)在**单一事务**内:bulk_create extracted
拿 id → name→id 映射(preset 优先)→ update_result 四维 → bulk_create shots → 解析 appearing
写 shot_characters(name 归一化失败跳过 + warning)→ set_current。任一步失败整体回滚(不留半截)。

失败 / 取消兜底:把 analysis 行标 `failed`(清 `has_inflight`,允许重发);`ProviderAuthFailed`
另把配置置 `invalid`(D8)。config 在发起时冻结(D9:运行期改 active 配置不影响在途任务)。
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Coroutine
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drama_smith.analysis.state import AnalysisState
from drama_smith.core.errors import InvalidState, ProviderAuthFailed, ScriptRequired
from drama_smith.db.base import get_session_factory
from drama_smith.db.models import EpisodeCharacter, Task
from drama_smith.db.repositories import (
    analysis_repo,
    episode_character_repo,
    episode_repo,
    script_repo,
    shot_repo,
    task_repo,
)
from drama_smith.graphs import build_analysis_graph, run_with_progress
from drama_smith.services import model_config_service
from drama_smith.tasks import ProgressCallback, TaskExecutor, Work

logger = logging.getLogger("drama_smith.analysis_service")

# 角色名归一化(D13):trim + 去标点 + lower,缓和别名 / 拼写漂移(CJK 为 \w,保留)。
_PUNCT = re.compile(r"[\W_]+", re.UNICODE)


def _norm_name(name: str) -> str:
    return _PUNCT.sub("", name.strip()).lower()


def _character_to_state(c: EpisodeCharacter) -> dict[str, Any]:
    """`EpisodeCharacter` → `AnalysisState.preset_characters` 项(带 db id,供落库 name→id 映射)。"""
    return {
        "episode_character_id": c.id,
        "name": c.name,
        "role_type": c.role_type,
        "persona": c.persona,
        "motivation": c.motivation,
        "traits": c.traits,
        "appearance_desc": c.appearance_desc,
    }


async def analyze(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    *,
    executor: TaskExecutor,
    mek: bytes,
    model_factory: model_config_service.ModelBuilder | None = None,
) -> Task:
    """发起拆解:门禁 + 串行约束 → 建 task/analysis(pending)→ 提交执行器 → 返回 task(202)。

    - 归属:`episode_repo.get`(`NotFound`)。
    - 门禁:`require_active_text`(`ModelNotConfigured`);无剧本 → `ScriptRequired`(422)。
    - 串行:`has_inflight` → `InvalidState`(409,D3)。
    `model_factory` 透传给 work 闭包,供测试注入替身(经 `build_text_model_from_config`)。
    """
    episode = await episode_repo.get(session, user_id, episode_id)
    config = await model_config_service.require_active_text(session, user_id)
    script = await script_repo.get(session, user_id, episode_id)  # 无 script 容器 → NotFound
    if script.current_version_id is None:
        raise ScriptRequired()
    version = await script_repo.get_version(session, user_id, script.current_version_id)
    if await analysis_repo.has_inflight(session, user_id, episode_id):
        raise InvalidState("An analysis is already in flight for this episode")

    config_snapshot: dict[str, Any] = {
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
    }
    preset_chars = [
        c
        for c in await episode_character_repo.list_by_episode(session, user_id, episode_id)
        if c.source == "preset"
    ]
    initial_state: dict[str, Any] = {
        "script": version.content,
        "script_format": version.format,
        "aspect_ratio": episode.aspect_ratio,
        "style_preset": episode.style_preset,
        "preset_characters": [_character_to_state(c) for c in preset_chars],
    }

    task = await task_repo.create(
        session,
        user_id,
        episode_id=episode_id,
        type="analyze",
        input_snapshot={
            "script_version_id": version.id,
            "model": config_snapshot,
            "preset_character_count": len(preset_chars),
        },
    )
    analysis = await analysis_repo.create(
        session,
        user_id,
        episode_id,
        script_version_id=version.id,
        config_snapshot=config_snapshot,
    )
    await session.commit()

    work = _make_analyze_work(
        user_id=user_id,
        episode_id=episode_id,
        task_id=task.id,
        analysis_id=analysis.id,
        config=config,  # 冻结(D9):work 用此 config,运行期改 active 不影响
        mek=mek,
        initial_state=initial_state,
        model_factory=model_factory,
    )
    await executor.submit(task.id, user_id, work)
    return task


async def get_analysis(session: AsyncSession, user_id: int, episode_id: int) -> dict[str, Any]:
    """双语义读(D11):`{current_analysis, inflight_task, stale_flag}`。

    - `current_analysis`:current 指针的分析(含 result)或 `None`;
    - `inflight_task`:该剧集在途 analyze 任务(pending/running)或 `None`;
    - `stale_flag`:current 所基于剧本版本 ≠ 当前剧本版本 → `True`(提示重拆,不阻断)。
    """
    current = await analysis_repo.get_current(session, user_id, episode_id)
    inflight = await task_repo.find_inflight_by_episode(
        session, user_id, episode_id, type="analyze"
    )
    stale = False
    if current is not None:
        script = await script_repo.get(session, user_id, episode_id)
        stale = script.current_version_id != current.script_version_id
    return {"current_analysis": current, "inflight_task": inflight, "stale_flag": stale}


async def select_current_analysis(
    session: AsyncSession, user_id: int, episode_id: int, analysis_id: int
) -> None:
    """切换 `current_analysis_id` 到指定历史 analysis(D11;analysis 须属本剧集)。"""
    episode = await episode_repo.get(session, user_id, episode_id)
    await analysis_repo.set_current(session, episode, analysis_id)
    await session.commit()


# ---- work 闭包 + 落库(executor 后台跑,开自己的 session)----


async def _persist_analysis(
    sf: async_sessionmaker[AsyncSession],
    user_id: int,
    episode_id: int,
    analysis_id: int,
    state: dict[str, Any],
) -> None:
    """拆解产出落库(D13,单事务):extracted 角色 → name→id 映射 → 四维 result → shots →
    appearing 解析写 shot_characters(失败跳过+warning)→ set_current。任一步失败整体回滚。"""
    async with sf() as session:
        analysis = await analysis_repo.get(session, user_id, analysis_id)
        # ① extracted 角色落库(source='analysis')拿 id
        extracted = list(state.get("characters") or [])
        extracted_ids: list[int] = []
        if extracted:
            extracted_ids = await episode_character_repo.bulk_create(
                session, user_id, episode_id, extracted, source="analysis"
            )
        # ② name → episode_character_id 映射(preset 优先;extracted 用 setdefault)
        name_to_id: dict[str, int] = {}
        for pc in state.get("preset_characters") or []:
            if pc.get("episode_character_id") is not None and pc.get("name"):
                name_to_id[_norm_name(pc["name"])] = pc["episode_character_id"]
        for ch, cid in zip(extracted, extracted_ids, strict=True):
            name = ch.get("name")
            if name:
                name_to_id.setdefault(_norm_name(name), cid)
        # ③ 四维 result(整体快照,D9)
        result = {
            "characters": extracted,
            "plotlines": state.get("plotlines") or [],
            "conflicts": state.get("conflicts") or [],
            "pacing": state.get("pacing") or {},
        }
        await analysis_repo.update_result(session, analysis, status="succeeded", result=result)
        # ④ shots 落库 + appearing 解析为 shot_characters(D13 外键解析,非角色合并)
        shots = list(state.get("shots") or [])
        shot_rows = await shot_repo.bulk_create(session, analysis_id, episode_id, shots)
        links: list[tuple[int, list[int]]] = []
        for shot_row, shot_dict in zip(shot_rows, shots, strict=True):
            char_ids: list[int] = []
            for name in shot_dict.get("appearing") or []:
                char_id = name_to_id.get(_norm_name(name))
                if char_id is None:
                    logger.warning(
                        "analysis=%s shot=%s: 角色 %r 未在已知清单,跳过关联(可经 PATCH 补)",
                        analysis_id,
                        shot_row.id,
                        name,
                    )
                    continue
                char_ids.append(char_id)
            if char_ids:
                links.append((shot_row.id, char_ids))
        if links:
            await shot_repo.bulk_link_characters(session, links)
        # ⑤ 移 current_analysis_id 指针(D11)
        episode = await episode_repo.get(session, user_id, episode_id)
        await analysis_repo.set_current(session, episode, analysis_id)
        await session.commit()


async def _mark_analysis_failed(
    sf: async_sessionmaker[AsyncSession], user_id: int, analysis_id: int
) -> None:
    """失败 / 取消兜底:analysis 行标 `failed`(清 `has_inflight`,允许重发)。best-effort。"""
    try:
        async with sf() as session:
            analysis = await analysis_repo.get(session, user_id, analysis_id)
            await analysis_repo.update_result(session, analysis, status="failed")
            await session.commit()
    except Exception:  # noqa: BLE001 — 兜底不应掩盖原异常
        logger.exception("analysis=%s 标 failed 失败(忽略,保留原异常)", analysis_id)


def _make_analyze_work(
    *,
    user_id: int,
    episode_id: int,
    task_id: int,
    analysis_id: int,
    config: Any,
    mek: bytes,
    initial_state: dict[str, Any],
    model_factory: model_config_service.ModelBuilder | None,
) -> Work:
    """构造 analyze 的 work 闭包(executor 后台跑):构模型 → 跑图(progress 适配)→ 落库。

    progress 适配:`run_with_progress` 吃 sync 回调、executor 的 `progress_cb` 是 async,故用
    `loop.create_task` fire-and-forget、图跑完 `gather` 排空;末尾自置 100(图最高 90)。
    """
    sf = get_session_factory()
    del task_id  # task 记录由 executor 管(progress_cb 已带 task_id);此处不直接用

    async def work(progress_cb: ProgressCallback) -> dict[str, Any] | None:
        text_model = model_config_service.build_text_model_from_config(
            config, mek, model_factory=model_factory
        )
        loop = asyncio.get_running_loop()
        pending: set[asyncio.Task[None]] = set()

        def on_progress(progress: int, stage: str) -> None:
            # progress_cb 是 Awaitable[None] 接缝(运行期即协程);
            # cast 后 create_task 才能推断 Task[None]
            task = loop.create_task(cast("Coroutine[Any, Any, None]", progress_cb(progress, stage)))
            pending.add(task)
            task.add_done_callback(pending.discard)

        try:
            compiled = build_analysis_graph(text_model)
            final = await run_with_progress(
                compiled, cast("AnalysisState", initial_state), on_progress
            )
            await asyncio.gather(*pending, return_exceptions=True)
            await _persist_analysis(sf, user_id, episode_id, analysis_id, final)
            await progress_cb(100, "persisting")
            return {"analysis_id": analysis_id}
        except ProviderAuthFailed:
            await model_config_service.mark_config_invalid(sf, user_id, config.id)
            await _mark_analysis_failed(sf, user_id, analysis_id)
            raise
        except asyncio.CancelledError:
            await _mark_analysis_failed(sf, user_id, analysis_id)
            raise
        except Exception:  # noqa: BLE001 — 任何异常都标 analysis failed,清 has_inflight
            await _mark_analysis_failed(sf, user_id, analysis_id)
            raise

    return work
