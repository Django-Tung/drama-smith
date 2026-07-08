"""结构化文本拆解:状态 / pydantic 输出模型 / Prompt 策略 / 图节点。

分层约束(design NFR-2):本包仅依赖 `core/llm` 的 `TextModel` Protocol 与 `core/errors`,
**绝不 import litellm / 厂商 SDK / crypto / services / graphs**(供应商无关接缝;
`graphs/` 负责把 `TextModel` 绑定进 LangGraph,本包只提供纯函数节点)。
"""

from __future__ import annotations

from drama_smith.analysis.models import (
    CharacterExtract,
    CharactersResult,
    Conflict,
    ConflictsResult,
    OptimizeResult,
    Pacing,
    PacingResult,
    Plotline,
    PlotlinesResult,
    ShotDraft,
    ShotsResult,
)
from drama_smith.analysis.state import AnalysisState, PresetCharacter

__all__ = [
    "AnalysisState",
    "CharacterExtract",
    "CharactersResult",
    "Conflict",
    "ConflictsResult",
    "OptimizeResult",
    "Pacing",
    "PacingResult",
    "Plotline",
    "PlotlinesResult",
    "PresetCharacter",
    "ShotDraft",
    "ShotsResult",
]
