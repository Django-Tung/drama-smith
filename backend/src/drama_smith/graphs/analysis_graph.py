"""LangGraph 分析图编排(D2)。

`START → extract_characters → fan-out(analyze_plot ‖ analyze_conflict ‖ analyze_pacing)
→ split_shots → END`。角色抽取是后续三步的 barrier(fan-out 前置);情节线 / 冲突 / 节奏三者
相互独立、LangGraph 并行(同一节点多条出边);split_shots 依赖四维全齐(多条入边 =
superstep barrier)。

节点是 `analysis.nodes` 的纯函数,经 `functools.partial` 绑定**单个贯穿整图的 `TextModel`**
(避免逐节点重复解密,D8)。进度归一:`NODE_PROGRESS` 把节点名映射为 `(progress, stage)`,
`run_with_progress` 经 `astream(stream_mode="updates")` 在节点完成时回调,供执行器写 task 记录。

分层(NFR-2):本模块 import langgraph + analysis + `core/llm` 的 `TextModel`,**不 import litellm**。
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from drama_smith.analysis import nodes
from drama_smith.analysis.state import AnalysisState
from drama_smith.llm.base import TextModel

# 节点名 → (进度%, 阶段名)归一(D2);三步并行各占 35%,split_shots 90%,收尾 100 由调用方置。
NODE_PROGRESS: dict[str, tuple[int, str]] = {
    "extract_characters": (10, "extracting_characters"),
    "analyze_plot": (35, "analyzing_plot"),
    "analyze_conflict": (35, "analyzing_conflict"),
    "analyze_pacing": (35, "analyzing_pacing"),
    "split_shots": (90, "splitting_shots"),
}

ProgressCallback = Callable[[int, str], None]


def build_analysis_graph(text_model: TextModel) -> Any:
    """构造编译后的分析图;`text_model` 经 partial 贯穿所有节点(D8 单模型贯穿整图)。"""
    graph = StateGraph(AnalysisState)
    graph.add_node("extract_characters", partial(nodes.extract_characters, text_model=text_model))
    graph.add_node("analyze_plot", partial(nodes.analyze_plot, text_model=text_model))
    graph.add_node("analyze_conflict", partial(nodes.analyze_conflict, text_model=text_model))
    graph.add_node("analyze_pacing", partial(nodes.analyze_pacing, text_model=text_model))
    graph.add_node("split_shots", partial(nodes.split_shots, text_model=text_model))

    graph.add_edge(START, "extract_characters")
    # fan-out:extract_characters 三条出边 → LangGraph 并行跑三个分析节点
    graph.add_edge("extract_characters", "analyze_plot")
    graph.add_edge("extract_characters", "analyze_conflict")
    graph.add_edge("extract_characters", "analyze_pacing")
    # barrier:三步各一条入边到 split_shots → superstep 等四维全齐再切分镜
    graph.add_edge("analyze_plot", "split_shots")
    graph.add_edge("analyze_conflict", "split_shots")
    graph.add_edge("analyze_pacing", "split_shots")
    graph.add_edge("split_shots", END)
    return graph.compile()


async def run_with_progress(
    compiled: Any,
    state: AnalysisState,
    on_progress: ProgressCallback,
) -> dict[str, Any]:
    """端到端跑图:节点完成时回调 `(progress, stage)`,返回合并后的最终 state。

    `stream_mode="updates"` 每步 yield `{node_name: state_delta}`;据 `NODE_PROGRESS` 归一进度。
    组7 执行器据此写 `task.progress` / `task.stage`(REST 可读)。
    """
    final: dict[str, Any] = dict(state)
    async for updates in compiled.astream(state, stream_mode="updates"):
        for node_name, delta in updates.items():
            if node_name in NODE_PROGRESS:
                progress, stage = NODE_PROGRESS[node_name]
                on_progress(progress, stage)
            if isinstance(delta, dict):
                final.update(delta)
    return final


__all__ = ["NODE_PROGRESS", "ProgressCallback", "build_analysis_graph", "run_with_progress"]
