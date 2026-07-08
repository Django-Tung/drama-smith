"""LangGraph 分析图共享状态(D2/D13)。

贯穿图执行期(纯内存):节点读输入字段、写产出字段。**角色与分镜出场一律以 `name` 为引用键**
——extracted 角色此时尚无 db id,落库事务(`analysis_service.persist`)内才解析为
`episode_character_id`(D13)。`preset_characters` 带 `episode_character_id` 供 service 落库时
建 `name→episode_character_id` 全集映射(preset 优先)。

`total=False` 以便 LangGraph 合并各节点的部分更新(节点只返回它写入的字段)。
"""

from __future__ import annotations

from typing import TypedDict


class PresetCharacter(TypedDict, total=False):
    """预置角色(state 内即有 db id);`episode_character_id` 供落库 name→id 映射(D13)。"""

    episode_character_id: int
    name: str
    role_type: str
    persona: str
    motivation: str
    traits: list[str]
    appearance_desc: str


class AnalysisState(TypedDict, total=False):
    """分析图状态:输入由 service 注入,产出由各节点写入。"""

    # 输入(图启动时注入)
    script: str
    script_format: str
    aspect_ratio: str
    style_preset: str
    preset_characters: list[PresetCharacter]
    # 产出(extract_characters → fan-out(plot/conflict/pacing) → split_shots)
    characters: list[dict]
    plotlines: list[dict]
    conflicts: list[dict]
    pacing: dict
    shots: list[dict]
