"""剧本仓储(与剧集 1:1;版本 append-only,[FR-A3](../../requirements/features/analysis.md))。

归属经 `episode → drama → user`。`current_version_id` 为逻辑指针(D11 心智,
与 `episodes.current_analysis_id` 同):本层仅置**已加载 script** 的指针,且目标版本须属该 script。
首次写剧本时 get-or-create script 容器,每次输入产 `source='input'` 新版本、`version_no` 自增、
移 `current_version_id`。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import Conflict, NotFound
from drama_smith.db.models import Drama, Episode, Script, ScriptVersion


async def _get_script(
    session: AsyncSession, user_id: int, episode_id: int
) -> Script | None:
    """JOIN `episode → drama` 校验归属;返回 script 或 `None`(不抛,供 get-or-create 区分)。"""
    stmt = (
        select(Script)
        .join(Episode, Script.episode_id == Episode.id)
        .join(Drama, Episode.drama_id == Drama.id)
        .where(
            Script.episode_id == episode_id,
            Drama.user_id == user_id,
            Episode.deleted_at.is_(None),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get(session: AsyncSession, user_id: int, episode_id: int) -> Script:
    """取剧集的 script 容器(1:1);归属经 episode→drama 校验。无 → `NotFound`。"""
    script = await _get_script(session, user_id, episode_id)
    if script is None:
        raise NotFound("Script not found")
    return script


async def _get_or_create_script(
    session: AsyncSession, user_id: int, episode_id: int
) -> Script:
    """取或建 script 容器;建前 JOIN 校验 episode 归属,并发撞 UNIQUE → `Conflict`。"""
    script = await _get_script(session, user_id, episode_id)
    if script is not None:
        return script
    # 校验 episode 归属(避免给他人的 episode 建容器);越权 → NotFound。
    stmt_ep = (
        select(Episode)
        .join(Drama, Episode.drama_id == Drama.id)
        .where(
            Episode.id == episode_id,
            Drama.user_id == user_id,
            Episode.deleted_at.is_(None),
        )
    )
    if (await session.execute(stmt_ep)).scalar_one_or_none() is None:
        raise NotFound("Episode not found")
    script = Script(episode_id=episode_id)
    session.add(script)
    try:
        await session.flush()  # 触发 scripts.episode_id UNIQUE
    except IntegrityError as exc:  # 并发:另一事务已建容器
        raise Conflict("Script container already exists") from exc
    await session.refresh(script)
    return script


async def upsert_input_version(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    *,
    content: str,
    format: str = "markdown",
) -> ScriptVersion:
    """写入剧本正文:取或建 script 容器 → 追加 `source='input'` 新版本(version_no 自增)
    → 移 `current_version_id` 指向新版本。"""
    script = await _get_or_create_script(session, user_id, episode_id)
    max_no = (
        await session.execute(
            select(func.max(ScriptVersion.version_no)).where(
                ScriptVersion.script_id == script.id
            )
        )
    ).scalar_one()
    version_no = (max_no or 0) + 1
    version = ScriptVersion(
        script_id=script.id,
        version_no=version_no,
        content=content,
        format=format,
        source="input",
    )
    session.add(version)
    await session.flush()
    script.current_version_id = version.id  # 逻辑指针:新版本即当前
    await session.flush()
    return version


async def add_optimize_version(
    session: AsyncSession,
    script: Script,
    *,
    content: str,
    format: str,
) -> ScriptVersion:
    """追加 `source='optimize'` 版本(AI 润色产出);调用方决定是否移 `current_version_id`(accept)。"""
    max_no = (
        await session.execute(
            select(func.max(ScriptVersion.version_no)).where(
                ScriptVersion.script_id == script.id
            )
        )
    ).scalar_one()
    version_no = (max_no or 0) + 1
    version = ScriptVersion(
        script_id=script.id,
        version_no=version_no,
        content=content,
        format=format,
        source="optimize",
    )
    session.add(version)
    await session.flush()
    return version


async def set_current_version(
    session: AsyncSession, script: Script, version_id: int
) -> None:
    """移当前版本指针(accept / revert);版本须属该 script,否则 `NotFound`。"""
    owned = (
        await session.execute(
            select(ScriptVersion.id).where(
                ScriptVersion.id == version_id,
                ScriptVersion.script_id == script.id,
            )
        )
    ).scalar_one_or_none()
    if owned is None:
        raise NotFound("Script version not found")
    script.current_version_id = version_id
    await session.flush()


async def list_versions(
    session: AsyncSession, user_id: int, episode_id: int
) -> list[ScriptVersion]:
    """列剧本全部版本(新→旧);归属经 script→episode→drama 校验。"""
    script = await get(session, user_id, episode_id)
    stmt = (
        select(ScriptVersion)
        .where(ScriptVersion.script_id == script.id)
        .order_by(ScriptVersion.version_no.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_version(
    session: AsyncSession, user_id: int, version_id: int
) -> ScriptVersion:
    """按 id 取版本;归属经 script→episode→drama 校验。越权 → `NotFound`。"""
    stmt = (
        select(ScriptVersion)
        .join(Script, ScriptVersion.script_id == Script.id)
        .join(Episode, Script.episode_id == Episode.id)
        .join(Drama, Episode.drama_id == Drama.id)
        .where(
            ScriptVersion.id == version_id,
            Drama.user_id == user_id,
            Episode.deleted_at.is_(None),
        )
    )
    version: ScriptVersion | None = (await session.execute(stmt)).scalar_one_or_none()
    if version is None:
        raise NotFound("Script version not found")
    return version
