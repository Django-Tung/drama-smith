"""拆解 / 优化的 Prompt 策略对象集合(design「Strategy = 模块化能力 / skills」)。

每项 LLM 能力一个 `PromptStrategy`:`build_messages`(构造提示)→ `output_model`(期望结构)
→ `response_format`(按 provider 选 JSON/退化)→ `parse`(解析 + 校验)。节点只编排这四步,
**不掺 prompt / 解析细节**;新增能力 = 新增一个策略实例,不动图骨架与 `core/llm` 接缝。

provider 适配(D2 风险):本期统一 `response_format={"type":"json_object"}`(OpenAI/GLM 兼容);
不支持 JSON mode 的供应商由 `parse` 层容错(去 ```json``` fence、提取首个平衡 `{...}` 片段)。
5.5 spike 验证真实模型后,provider 差异化 / 解析重试只在本层调整——这是铠甲轻重的落点。
解析失败统一抛 `AnalysisParseError`(service 捕获 → 任务 failed,不 500 挂起)。

提示工程:全部提示集中于此(可 review、**不含明文 Key**);copy-edit 与拆解提示分离(D12);
`split_shots` 的 prompt 含已知角色名清单约束,要求 `appearing` 仅从中选、输出 name(D13)。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Protocol, cast, runtime_checkable

from pydantic import BaseModel, ValidationError

from drama_smith.analysis.models import (
    CharactersResult,
    ConflictsResult,
    OptimizeResult,
    PacingResult,
    PlotlinesResult,
    ShotsResult,
)
from drama_smith.analysis.state import AnalysisState
from drama_smith.core.errors import AnalysisParseError

# 模型常把 JSON 包在 ```json ... ``` 里或前后带解释文字;按 fence 优先、否则截首个平衡 {} 片段。
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(raw: str) -> str:
    """从模型原始输出里提取首个 JSON 对象文本(去 markdown fence / 前后噪声)。"""
    text = raw.strip()
    if fence := _JSON_FENCE.search(text):
        return fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    # 不平衡 → 返回 start 起的片段,交给 json.loads 给出清晰错误
    return text[start:]


@runtime_checkable
class PromptStrategy(Protocol):
    """模块化 LLM 能力策略(design「Strategy = skills」)的契约。"""

    name: str
    output_model: type[BaseModel]

    def build_messages(self, ctx: AnalysisState) -> list[Mapping[str, str]]: ...
    def response_format(self, provider: str = "") -> dict | None: ...
    def parse(self, raw: str) -> BaseModel: ...


class JsonPromptStrategy[T: BaseModel]:
    """通用基类:统一 `response_format` + `parse`(JSON 提取 + pydantic 校验)。

    子类只给 `name` / `output_model` / `build_messages`;`parse` 失败映射 `AnalysisParseError`。
    `response_format` 本期统一返回 OpenAI 兼容 JSON mode(provider 差异化留 5.5 spike 后)。
    """

    name: str = ""
    output_model: type[T]

    def response_format(self, provider: str = "") -> dict | None:
        del provider  # 本期不分化;spike 后可按 provider 选 json_object / tool / None
        return {"type": "json_object"}

    def parse(self, raw: str) -> T:
        snippet = _extract_json(raw)
        try:
            data = json.loads(snippet)
        except json.JSONDecodeError as exc:
            raise AnalysisParseError(
                f"{self.name}: model output is not valid JSON",
                details={"snippet": snippet[:200]},
            ) from exc
        try:
            return cast("T", self.output_model.model_validate(data))
        except ValidationError as exc:
            raise AnalysisParseError(
                f"{self.name}: structured output failed schema validation",
                details={"errors": exc.errors()},
            ) from exc


def _ctx_line(ctx: AnalysisState) -> str:
    """画幅 / 风格上下文片段,嵌入各拆解 prompt。"""
    parts = [f"画幅={ctx.get('aspect_ratio') or '未指定'}"]
    if ctx.get("style_preset"):
        parts.append(f"风格={ctx['style_preset']}")
    return "、".join(parts)


def _preset_names(ctx: AnalysisState) -> list[str]:
    return [p["name"] for p in (ctx.get("preset_characters") or []) if p.get("name")]


def _extracted_names(ctx: AnalysisState) -> list[str]:
    return [c["name"] for c in (ctx.get("characters") or []) if c.get("name")]


class _ExtractCharacters(JsonPromptStrategy[CharactersResult]):
    name = "extract_characters"
    output_model = CharactersResult

    def build_messages(self, ctx: AnalysisState) -> list[Mapping[str, str]]:
        preset = _preset_names(ctx)
        system = (
            "你是剧本结构分析师。从给定剧本中抽取所有出场角色。"
            "只输出一个 JSON 对象,键 `characters`,值为角色对象数组;"
            "每个角色含:name(必填)、role_type、persona、motivation、traits(字符串数组)、"
            "appearance_desc。不要输出任何 JSON 以外的文字。"
        )
        user = f"上下文:{_ctx_line(ctx)}\n"
        if preset:
            user += f"用户已预置角色(供参考、勿遗漏):{', '.join(preset)}\n"
        user += f"\n剧本:\n{ctx.get('script') or ''}"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]


class _AnalyzePlot(JsonPromptStrategy[PlotlinesResult]):
    name = "analyze_plot"
    output_model = PlotlinesResult

    def build_messages(self, ctx: AnalysisState) -> list[Mapping[str, str]]:
        known = _extracted_names(ctx)
        system = (
            "你是剧本结构分析师。梳理剧本的情节线(主线 / 副线 / 暗线)。"
            "只输出一个 JSON 对象,键 `plotlines`,值为情节线对象数组;"
            "每个含:name、type、scenes、trend。不要输出任何 JSON 以外的文字。"
        )
        user = f"上下文:{_ctx_line(ctx)}\n"
        if known:
            user += f"已知角色:{', '.join(known)}\n"
        user += f"\n剧本:\n{ctx.get('script') or ''}"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]


class _AnalyzeConflict(JsonPromptStrategy[ConflictsResult]):
    name = "analyze_conflict"
    output_model = ConflictsResult

    def build_messages(self, ctx: AnalysisState) -> list[Mapping[str, str]]:
        known = _extracted_names(ctx)
        system = (
            "你是剧本结构分析师。识别剧本中的冲突(人 vs 人 / 人 vs 环境 / 内心 等)。"
            "只输出一个 JSON 对象,键 `conflicts`,值为冲突对象数组;"
            "每个含:type、parties、intensity、resolution。不要输出任何 JSON 以外的文字。"
        )
        user = f"上下文:{_ctx_line(ctx)}\n"
        if known:
            user += f"已知角色:{', '.join(known)}\n"
        user += f"\n剧本:\n{ctx.get('script') or ''}"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]


class _AnalyzePacing(JsonPromptStrategy[PacingResult]):
    name = "analyze_pacing"
    output_model = PacingResult

    def build_messages(self, ctx: AnalysisState) -> list[Mapping[str, str]]:
        system = (
            "你是剧本结构分析师。诊断剧本的节奏与结构(advisory:仅描述、不改写文本)。"
            "只输出一个 JSON 对象,键 `pacing`,值为对象,含:"
            "structure(幕结构)、climax(高潮点)、density(节奏密度)、imbalance(失衡诊断)。"
            "不要输出任何 JSON 以外的文字。"
        )
        user = f"上下文:{_ctx_line(ctx)}\n\n剧本:\n{ctx.get('script') or ''}"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]


class _SplitShots(JsonPromptStrategy[ShotsResult]):
    name = "split_shots"
    output_model = ShotsResult

    def build_messages(self, ctx: AnalysisState) -> list[Mapping[str, str]]:
        known = [*_preset_names(ctx), *_extracted_names(ctx)]
        system = (
            "你是分镜导演。把整段剧本按剧情节拍切分成连续的分镜序列。"
            "只输出一个 JSON 对象,键 `shots`,值为分镜对象数组(按时间顺序);"
            "每个分镜含:description(必填)、shot_type(wide/medium/close/extreme_close 之一)、"
            "scene、plot_point、appearing(出场角色名数组)、dialogue、"
            "target_duration(该镜目标时长秒数,3–15 之间,按节拍估算)、camera_move、"
            "related_plotline、related_conflict。"
            "`appearing` 只能使用「已知角色清单」中的名字,不要编造新角色名。"
            "不要输出任何 JSON 以外的文字。"
        )
        user = f"上下文:{_ctx_line(ctx)}\n"
        if known:
            user += f"已知角色清单(appearing 只能从中选):{', '.join(known)}\n"
        user += f"\n剧本:\n{ctx.get('script') or ''}"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]


class _OptimizeCopyEdit(JsonPromptStrategy[OptimizeResult]):
    name = "optimize_copyedit"
    output_model = OptimizeResult

    def build_messages(self, ctx: AnalysisState) -> list[Mapping[str, str]]:
        fmt = ctx.get("script_format") or "plain"
        system = (
            "你是剧本文字编辑。对剧本做 copy-edit 润色:仅修正格式、错别字、标点与对白口吻,"
            "保持原文结构与段落对应。**不要重写、不要重排、不要增删场景或调整结构**"
            "(节奏 / 结构诊断属于另一维度,不在此处理)。"
            "只输出一个 JSON 对象,键 `content`,值为润色后的完整剧本正文。"
            "不要输出任何 JSON 以外的文字。"
        )
        user = f"剧本格式:{fmt}\n\n剧本:\n{ctx.get('script') or ''}"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# 模块级单例:节点 / service 经此引用(可单测、可按 provider 调整)。注解为具体泛型,
# 使节点 `_invoke` 能据策略推断 `parse` 的结构化返回类型(`PromptStrategy` 仅作异构集合契约)。
EXTRACT_CHARACTERS: JsonPromptStrategy[CharactersResult] = _ExtractCharacters()
ANALYZE_PLOT: JsonPromptStrategy[PlotlinesResult] = _AnalyzePlot()
ANALYZE_CONFLICT: JsonPromptStrategy[ConflictsResult] = _AnalyzeConflict()
ANALYZE_PACING: JsonPromptStrategy[PacingResult] = _AnalyzePacing()
SPLIT_SHOTS: JsonPromptStrategy[ShotsResult] = _SplitShots()
OPTIMIZE_COPYEDIT: JsonPromptStrategy[OptimizeResult] = _OptimizeCopyEdit()

STRATEGIES: dict[str, PromptStrategy] = {
    EXTRACT_CHARACTERS.name: EXTRACT_CHARACTERS,
    ANALYZE_PLOT.name: ANALYZE_PLOT,
    ANALYZE_CONFLICT.name: ANALYZE_CONFLICT,
    ANALYZE_PACING.name: ANALYZE_PACING,
    SPLIT_SHOTS.name: SPLIT_SHOTS,
    OPTIMIZE_COPYEDIT.name: OPTIMIZE_COPYEDIT,
}


__all__ = [
    "ANALYZE_CONFLICT",
    "ANALYZE_PACING",
    "ANALYZE_PLOT",
    "EXTRACT_CHARACTERS",
    "JsonPromptStrategy",
    "OPTIMIZE_COPYEDIT",
    "PromptStrategy",
    "SPLIT_SHOTS",
    "STRATEGIES",
]
