"""LangGraph 分析图端到端编排测试(任务 6.4)。

用按 system 提示路由的 `TextModel` 替身(兼容 fan-out 三节点并行乱序),验证建图拓扑
(extract → fan-out(plot‖conflict‖pacing) → split_shots)端到端产出四维 + 分镜、split_shots
以 name 引用角色(D13)、以及 `run_with_progress` 对每个节点回调 `(progress, stage)`。
纯单元(无 DB / 无网络)。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from drama_smith.graphs import build_analysis_graph, run_with_progress


class _RoutingTextModel:
    """据 system 提示关键词路由返回对应维度 JSON 的替身(并行节点乱序亦能正确分发)。"""

    async def chat(self, messages: Sequence[Mapping[str, str]], **params: Any) -> str:
        del params
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        # 路由顺序有讲究:split_shots 的 system 含「角色」(已知角色清单),须先被「分镜」截走,
        # 否则会误路由到 characters;「角色」放最后只匹配 extract_characters。
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


def _input() -> dict[str, Any]:
    return {
        "script": "第一幕:小明走进咖啡馆,遇见阿珍。",
        "aspect_ratio": "16:9",
        "preset_characters": [{"episode_character_id": 1, "name": "小明"}],
    }


async def test_graph_end_to_end() -> None:
    final = await build_analysis_graph(_RoutingTextModel()).ainvoke(_input())
    assert final["characters"][0]["name"] == "小明"
    assert final["plotlines"][0]["name"] == "主线"
    assert final["conflicts"][0]["type"] == "人vs人"
    assert final["pacing"]["structure"] == "三幕"
    assert final["shots"][0]["appearing"] == ["小明"]  # D13:name 引用,非 db id


async def test_run_with_progress_reports_each_node() -> None:
    events: list[tuple[int, str]] = []
    final = await run_with_progress(
        build_analysis_graph(_RoutingTextModel()),
        _input(),
        lambda progress, stage: events.append((progress, stage)),
    )
    assert len(events) == 5  # 五个节点各回调一次
    assert (10, "extracting_characters") in events
    assert (90, "splitting_shots") in events
    assert final["shots"][0]["appearing"] == ["小明"]


async def test_text_model_bound_once_across_graph() -> None:
    # D8:同一 TextModel 贯穿整图;5 个节点调用都经同一实例(chat_calls 累计 = 节点数)
    model = _RoutingTextModel()
    calls = {"n": 0}
    chat = model.chat

    async def counting(messages: Sequence[Mapping[str, str]], **params: Any) -> str:
        calls["n"] += 1
        return await chat(messages, **params)

    model.chat = counting  # type: ignore[method-assign]
    await build_analysis_graph(model).ainvoke(_input())
    assert calls["n"] == 5
