"""剧本用例编排(版本指针 + AI 优化产出落版本,D6/D9/D12)。

事务边界在此(D14):repo 只 `flush`,用例 `commit`。版本 append-only:`upsert_script`
产 `source='input'` 版本并移 `current_version_id`;`select_version`(=accept=revert)移指针;
`reject_version` 显式 no-op(版本保留,不动指针,D6)。

`diff_versions` 为纯函数(D12):optimize 任务 succeeded 后用标准库 `difflib` 算段落级 diff,
经任务 `output_refs` 返回、**不落库**;前端只读渲染、整版采纳。段落切分按 `format` 分派
(plain=空行、markdown=标题或空行、fountain=场景头或空行),不引 fountain parser。
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.analysis.prompts import OPTIMIZE_COPYEDIT
from drama_smith.analysis.state import AnalysisState
from drama_smith.core.errors import ProviderAuthFailed, ScriptRequired
from drama_smith.db.base import get_session_factory
from drama_smith.db.models import Script, ScriptVersion, Task
from drama_smith.db.repositories import script_repo, task_repo
from drama_smith.services import model_config_service
from drama_smith.tasks import ProgressCallback, TaskExecutor, Work

# markdown 标题行(`# ` ~ `###### `);fountain 场景头(INT./EXT./EST. 或 INT/EXT)。
_MD_HEADING = re.compile(r"#{1,6}\s")
_FOUNTAIN_SCENE = re.compile(r"(?:INT|EXT|EST)[./]", re.IGNORECASE)


def _segment(text: str, head_re: re.Pattern[str] | None) -> list[str]:
    """切段落:空行(1+ 空行)为段界;若给 `head_re`,行首匹配(标题/场景头)亦开新段。

    多个连续空行塌缩为单一边界;首尾空白忽略。markdown 下标题与其后正文同段(成节),
    fountain 下场景头与其后内容同段(成场)。
    """
    segments: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        if line.strip() == "":
            if any(s.strip() for s in current):
                segments.append("\n".join(current).strip())
                current = []
            continue
        if head_re is not None and head_re.match(line) and any(s.strip() for s in current):
            segments.append("\n".join(current).strip())
            current = []
        current.append(line)
    if any(s.strip() for s in current):
        segments.append("\n".join(current).strip())
    return segments


def _split(text: str, format: str) -> list[str]:
    """按剧本格式分派切分器;未知格式退化为 plain(空行)。"""
    if format == "markdown":
        return _segment(text, _MD_HEADING)
    if format == "fountain":
        return _segment(text, _FOUNTAIN_SCENE)
    return _segment(text, None)


def diff_versions(before: str, after: str, *, format: str) -> list[dict[str, Any]]:
    """段落级 diff(D12):按 `format` 切段 → `SequenceMatcher` 对齐 → 映射 `change_type`。

    返回 `[{seg, before, after, change_type}]`(`seg` 为 1-based 连续序号):
    - `unchanged`:段两侧相同;
    - `modified`:对位段两侧均有内容但不同;
    - `added`:`before=""`(仅 after 有);
    - `removed`:`after=""`(仅 before 有)。
    `replace` 块内长度不等时按位配对、多出段按 add/remove 收尾。
    """
    before_segs = _split(before, format)
    after_segs = _split(after, format)
    matcher = difflib.SequenceMatcher(a=before_segs, b=after_segs, autojunk=False)
    diffs: list[dict[str, Any]] = []
    seg_no = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for seg in before_segs[i1:i2]:
                seg_no += 1
                diffs.append(
                    {"seg": seg_no, "before": seg, "after": seg, "change_type": "unchanged"}
                )
        elif tag == "replace":
            bs, as_ = before_segs[i1:i2], after_segs[j1:j2]
            for k in range(max(len(bs), len(as_))):
                seg_no += 1
                b = bs[k] if k < len(bs) else ""
                a = as_[k] if k < len(as_) else ""
                if b and a:
                    change = "modified"
                elif a:
                    change = "added"
                else:
                    change = "removed"
                diffs.append({"seg": seg_no, "before": b, "after": a, "change_type": change})
        elif tag == "delete":
            for seg in before_segs[i1:i2]:
                seg_no += 1
                diffs.append({"seg": seg_no, "before": seg, "after": "", "change_type": "removed"})
        elif tag == "insert":
            for seg in after_segs[j1:j2]:
                seg_no += 1
                diffs.append({"seg": seg_no, "before": "", "after": seg, "change_type": "added"})
    return diffs


async def upsert_script(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    *,
    content: str,
    format: str = "markdown",
) -> ScriptVersion:
    """写入剧本正文:取或建 script 容器 → 追加 `source='input'` 版本并移 current 指针。"""
    version = await script_repo.upsert_input_version(
        session, user_id, episode_id, content=content, format=format
    )
    await session.commit()
    return version


async def get_script(session: AsyncSession, user_id: int, episode_id: int) -> Script:
    """取剧集的 script 容器(1:1);无 → `NotFound`。"""
    return await script_repo.get(session, user_id, episode_id)


async def list_versions(
    session: AsyncSession, user_id: int, episode_id: int
) -> list[ScriptVersion]:
    """列剧本全部版本(新→旧)。"""
    return await script_repo.list_versions(session, user_id, episode_id)


async def get_version(session: AsyncSession, user_id: int, version_id: int) -> ScriptVersion:
    """按 id 取版本(归属校验);越权 → `NotFound`。"""
    return await script_repo.get_version(session, user_id, version_id)


async def select_version(
    session: AsyncSession, user_id: int, episode_id: int, version_id: int
) -> None:
    """采纳 / 回退:移 `current_version_id` 到指定版本(版本须属该剧本)。"""
    script = await script_repo.get(session, user_id, episode_id)
    await script_repo.set_current_version(session, script, version_id)
    await session.commit()


async def reject_version(
    session: AsyncSession, user_id: int, episode_id: int, version_id: int
) -> None:
    """拒绝采纳:不动指针、版本保留(可回看/回退)。仅校验归属,显式 no-op(D6)。"""
    await script_repo.get(session, user_id, episode_id)
    await script_repo.get_version(session, user_id, version_id)


async def optimize_script(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    *,
    executor: TaskExecutor,
    mek: bytes,
    model_factory: model_config_service.ModelBuilder | None = None,
) -> Task:
    """发起 copy-edit 润色(D12):门禁 + 取 current 版本 → 建 task → 提交执行器 → 返回 task(202)。

    - 门禁:`require_active_text`(`ModelNotConfigured`);无 current 版本 → `ScriptRequired`(422)。
    - 无串行约束(optimize 不锁剧集:产出落新版本、不移指针,可多次并行;重复只是多版本)。
    - config 在发起时冻结(D9):work 用此 config,运行期改 active 不影响在途任务。
    `model_factory` 透传给 work 闭包,供测试注入替身(经 `build_text_model_from_config`)。
    """
    config = await model_config_service.require_active_text(session, user_id)
    script = await script_repo.get(session, user_id, episode_id)  # 无 script 容器 → NotFound(404)
    if script.current_version_id is None:
        raise ScriptRequired()
    version = await script_repo.get_version(session, user_id, script.current_version_id)

    task = await task_repo.create(
        session,
        user_id,
        episode_id=episode_id,
        type="optimize",
        input_snapshot={
            "script_version_id": version.id,
            "model": {
                "provider": config.provider,
                "model": config.model,
                "base_url": config.base_url,
            },
        },
    )
    await session.commit()

    work = _make_optimize_work(
        user_id=user_id,
        episode_id=episode_id,
        config=config,  # 冻结(D9)
        mek=mek,
        before=version.content,
        fmt=version.format,
        model_factory=model_factory,
    )
    await executor.submit(task.id, user_id, work)
    return task


def _make_optimize_work(
    *,
    user_id: int,
    episode_id: int,
    config: Any,
    mek: bytes,
    before: str,
    fmt: str,
    model_factory: model_config_service.ModelBuilder | None,
) -> Work:
    """构造 optimize 的 work 闭包(executor 后台跑):构模型 → copy-edit → 落新版本 + diff。

    产出 `source='optimize'` 新版本在**任务 succeeded 时**写、不移 current 指针(accept 是
    之后的同步 `select_version`)。无 analysis 行,失败仅 task 记终态;`ProviderAuthFailed` →
    置配置 `invalid`(D8)。chat 调用照 `analysis.nodes._invoke` 的模式透传 `response_format`。
    """
    sf = get_session_factory()

    async def work(progress_cb: ProgressCallback) -> dict[str, Any] | None:
        text_model = model_config_service.build_text_model_from_config(
            config, mek, model_factory=model_factory
        )
        await progress_cb(50, "optimizing")
        try:
            state: AnalysisState = {"script": before, "script_format": fmt}
            response_format = OPTIMIZE_COPYEDIT.response_format()
            params: dict[str, Any] = {}
            if response_format is not None:
                params["response_format"] = response_format
            messages = OPTIMIZE_COPYEDIT.build_messages(state)  # type: ignore[attr-defined]
            raw = await text_model.chat(messages, **params)
            optimized = OPTIMIZE_COPYEDIT.parse(raw).content
            diff = diff_versions(before, optimized, format=fmt)
            async with sf() as s:
                script = await script_repo.get(s, user_id, episode_id)
                new_v = await script_repo.add_optimize_version(
                    s, script, content=optimized, format=fmt
                )  # 不移指针(accept 是后续 select_version)
                await s.commit()
            await progress_cb(100, "done")
            return {"version_id": new_v.id, "diff": diff}
        except ProviderAuthFailed:
            await model_config_service.mark_config_invalid(sf, user_id, config.id)
            raise

    return work
