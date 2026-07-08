"""分析图节点(纯函数,只编排策略四步,不掺 prompt / 解析细节)。

节点签名 `(state, text_model) -> dict[str, Any]`:组6 的 `build_analysis_graph` 用
`functools.partial` 把 `TextModel` 绑定进 LangGraph;本包**不 import langgraph**(纯函数,
可脱离图框架单测)。节点仅消费 `TextModel` Protocol,绝不 import litellm(NFR-2,分层自检)。

编排:`_invoke` = 策略 `build_messages` → `TextModel.chat(messages, response_format=...)` →
策略 `parse` → 返回结构化模型;各节点把模型 `.model_dump()` 写回 `AnalysisState` 对应字段。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from drama_smith.analysis import prompts
from drama_smith.analysis.prompts import JsonPromptStrategy
from drama_smith.analysis.state import AnalysisState
from drama_smith.llm.base import TextModel


async def _invoke[T: BaseModel](
    strategy: JsonPromptStrategy[T], state: AnalysisState, text_model: TextModel
) -> T:
    """单节点通用编排:构造提示 → 调模型(透传 response_format)→ 解析校验。"""
    response_format = strategy.response_format()
    params: dict[str, Any] = {}
    if response_format is not None:
        params["response_format"] = response_format
    raw = await text_model.chat(strategy.build_messages(state), **params)
    return strategy.parse(raw)


async def extract_characters(state: AnalysisState, text_model: TextModel) -> dict[str, Any]:
    """角色抽取(fan-out 前置 barrier):产 `characters`(name 引用,落库解析 id)。"""
    parsed = await _invoke(prompts.EXTRACT_CHARACTERS, state, text_model)
    return {"characters": [c.model_dump() for c in parsed.characters]}


async def analyze_plot(state: AnalysisState, text_model: TextModel) -> dict[str, Any]:
    """情节线分析(与冲突/节奏并行)。"""
    parsed = await _invoke(prompts.ANALYZE_PLOT, state, text_model)
    return {"plotlines": [p.model_dump() for p in parsed.plotlines]}


async def analyze_conflict(state: AnalysisState, text_model: TextModel) -> dict[str, Any]:
    """冲突分析(与情节线/节奏并行)。"""
    parsed = await _invoke(prompts.ANALYZE_CONFLICT, state, text_model)
    return {"conflicts": [c.model_dump() for c in parsed.conflicts]}


async def analyze_pacing(state: AnalysisState, text_model: TextModel) -> dict[str, Any]:
    """节奏 / 结构诊断(advisory,不改文本,D12)。"""
    parsed = await _invoke(prompts.ANALYZE_PACING, state, text_model)
    return {"pacing": parsed.pacing.model_dump()}


async def split_shots(state: AnalysisState, text_model: TextModel) -> dict[str, Any]:
    """切分镜(依赖四维):`appearing` 仅 name 引用、从已知角色清单选(D13)。"""
    parsed = await _invoke(prompts.SPLIT_SHOTS, state, text_model)
    return {"shots": [s.model_dump() for s in parsed.shots]}


__all__ = [
    "analyze_conflict",
    "analyze_pacing",
    "analyze_plot",
    "extract_characters",
    "split_shots",
]
