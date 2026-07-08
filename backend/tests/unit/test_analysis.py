"""分析图节点单测(任务 5.6)。

用 `FakeTextModel`(tests/llm/fakes,确定性输出)回放固定原始 JSON,覆盖各节点输入→输出、
`response_format` 透传、JSON 提取容错(去 markdown fence)、结构化解析失败 →
`AnalysisParseError`(非法 JSON / schema 不合 / 缺必填)、`split_shots` 以 name 引用角色(D13)、
split_shots prompt 含已知角色清单约束、以及各策略 prompt 不含明文 Key。
纯单元(无 DB / 无网络),替身驱动。
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.llm.fakes import FakeTextModel

from drama_smith.analysis import nodes, prompts
from drama_smith.analysis.prompts import PromptStrategy
from drama_smith.analysis.state import AnalysisState
from drama_smith.core.errors import AnalysisParseError


def _state(**kw: Any) -> AnalysisState:
    base: dict[str, Any] = {
        "script": "第一幕:小明走进咖啡馆,遇见阿珍。",
        "script_format": "plain",
        "aspect_ratio": "16:9",
        "style_preset": None,
        "preset_characters": [],
        "characters": [],
    }
    base.update(kw)
    return base  # type: ignore[return-value]


def _model(raw: str) -> FakeTextModel:
    return FakeTextModel(output=raw)


# ---- 各节点输入 → 输出 ----
async def test_extract_characters() -> None:
    out = await nodes.extract_characters(
        _state(), _model('{"characters":[{"name":"小明","role_type":"主角","traits":["沉稳"]}]}')
    )
    assert [c["name"] for c in out["characters"]] == ["小明"]
    assert out["characters"][0]["traits"] == ["沉稳"]


async def test_analyze_plot() -> None:
    out = await nodes.analyze_plot(
        _state(),
        _model('{"plotlines":[{"name":"主线","type":"主线","scenes":"全剧","trend":"上升"}]}'),
    )
    assert out["plotlines"][0]["name"] == "主线"


async def test_analyze_conflict() -> None:
    out = await nodes.analyze_conflict(
        _state(), _model('{"conflicts":[{"type":"人vs人","parties":"小明 vs 阿珍"}]}')
    )
    assert out["conflicts"][0]["type"] == "人vs人"


async def test_analyze_pacing() -> None:
    out = await nodes.analyze_pacing(
        _state(), _model('{"pacing":{"structure":"三幕","climax":"相遇","density":"紧凑"}}')
    )
    assert out["pacing"]["structure"] == "三幕"


async def test_split_shots_appearing_by_name() -> None:
    # D13:appearing 仅以 name 引用,不输出 db id
    state = _state(preset_characters=[{"episode_character_id": 7, "name": "小明"}])
    out = await nodes.split_shots(
        state,
        _model('{"shots":[{"description":"小明进门","appearing":["小明"],"target_duration":5}]}'),
    )
    assert out["shots"][0]["appearing"] == ["小明"]  # name,非 id
    assert out["shots"][0]["target_duration"] == 5


# ---- response_format 透传 + JSON fence 容错 ----
async def test_response_format_transmitted() -> None:
    model = _model('{"characters":[]}')
    await nodes.extract_characters(_state(), model)
    assert model.last_params.get("response_format") == {"type": "json_object"}


async def test_parse_strips_json_fence() -> None:
    out = await nodes.extract_characters(
        _state(), _model('```json\n{"characters":[{"name":"小明"}]}\n```')
    )
    assert out["characters"][0]["name"] == "小明"


# ---- 解析失败 → AnalysisParseError ----
async def test_parse_invalid_json_raises() -> None:
    with pytest.raises(AnalysisParseError):
        await nodes.extract_characters(_state(), _model("这不是 JSON"))


async def test_parse_schema_mismatch_raises() -> None:
    # characters 应为数组,这里给字符串 → schema 校验失败
    with pytest.raises(AnalysisParseError):
        await nodes.extract_characters(_state(), _model('{"characters":"oops"}'))


async def test_parse_missing_required_field_raises() -> None:
    # ShotDraft.description 必填;缺省 → 校验失败
    with pytest.raises(AnalysisParseError):
        await nodes.split_shots(_state(), _model('{"shots":[{"target_duration":5}]}'))


# ---- split_shots prompt 含已知角色清单约束(D13)----
def test_split_shots_prompt_lists_known_characters() -> None:
    state = _state(
        preset_characters=[{"episode_character_id": 1, "name": "小明"}],
        characters=[{"name": "阿珍"}],
    )
    body = prompts.SPLIT_SHOTS.build_messages(state)[-1]["content"]
    assert "小明" in body and "阿珍" in body  # 预置 + 抽取角色名都进清单
    assert "appearing" in body  # 约束:只能从清单选


# ---- prompts 不含明文 Key(任务 5.6)----
@pytest.mark.parametrize(
    "strategy",
    [
        prompts.EXTRACT_CHARACTERS,
        prompts.ANALYZE_PLOT,
        prompts.ANALYZE_CONFLICT,
        prompts.ANALYZE_PACING,
        prompts.SPLIT_SHOTS,
        prompts.OPTIMIZE_COPYEDIT,
    ],
)
def test_prompts_contain_no_plaintext_key(strategy: PromptStrategy) -> None:
    body = "".join(m["content"] for m in strategy.build_messages(_state()))
    lowered = body.lower()
    for needle in ("sk-", "api_key", "apikey", "bearer", "anthropic_api_key", "zhipuai_api_key"):
        assert needle not in lowered
