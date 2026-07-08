"""结构化拆解的 pydantic 输出模型(D2/D9)。

四维(角色/情节线/冲突/节奏)+ 分镜草稿,供 `chat()` 结构化约束与 `PromptStrategy.parse`
校验。**字段类型刻意宽松**(str 而非 Literal 枚举):业务枚举值范围(shot_type 等)与
target_duration 3–15s 越界由 service 落库时兜底(标注/归一,**不阻断**),解析层只校验
结构——对齐 D5「越界标注不阻断」与 D13「name 漂移跳过」精神。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class _Loose(BaseModel):
    """公共配置:忽略模型多输出的未知字段(供应商输出常带额外键)。"""

    model_config = {"extra": "ignore"}


class CharacterExtract(_Loose):
    """拆解抽取的角色(D7/D9):`name` 为 state 内引用键,落库才解析为 episode_character_id。"""

    name: str = Field(description="角色名(state 内引用键,落库解析为 episode_character_id)")
    role_type: str | None = Field(default=None, description="角色类型(主角/配角/反派 等)")
    persona: str | None = Field(default=None, description="人设概述")
    motivation: str | None = Field(default=None, description="核心动机")
    traits: list[str] | None = Field(default=None, description="性格特征标签")
    appearance_desc: str | None = Field(
        default=None, description="外貌描述(M3 随 media 绑定形象参考)"
    )


class CharactersResult(_Loose):
    characters: list[CharacterExtract] = Field(default_factory=list)


class Plotline(_Loose):
    """情节线(D9)。"""

    name: str = Field(description="情节线名称")
    type: str = Field(description="主线/副线/暗线 等")
    scenes: str | None = Field(default=None, description="涉及的场景/章节概述")
    trend: str | None = Field(default=None, description="走向(上升/缓和/收束 等)")


class PlotlinesResult(_Loose):
    plotlines: list[Plotline] = Field(default_factory=list)


class Conflict(_Loose):
    """冲突(D9)。"""

    type: str = Field(description="冲突类型(人vs人/人vs环境/内心 等)")
    parties: str | None = Field(default=None, description="冲突方")
    intensity: str | None = Field(default=None, description="强度描述")
    resolution: str | None = Field(default=None, description="解决方式或悬置状态")


class ConflictsResult(_Loose):
    conflicts: list[Conflict] = Field(default_factory=list)


class Pacing(_Loose):
    """节奏维度(D9):幕结构/高潮/密度/失衡诊断。advisory,不改文本(D12)。"""

    structure: str = Field(description="幕结构(如 三幕/起承转合)")
    climax: str | None = Field(default=None, description="高潮点")
    density: str | None = Field(default=None, description="节奏密度诊断")
    imbalance: str | None = Field(default=None, description="失衡诊断(advisory,供用户参考)")


class PacingResult(_Loose):
    pacing: Pacing


class ShotDraft(_Loose):
    """分镜草稿(D5/D9/D13):`appearing` 仅以角色 name 引用(落库解析为 episode_character_id)。

    target_duration 由文本模型估算,提示要求 3–15s;模型满足不了时可能越界或缺省,解析层放行、
    service 落库后标注(D5 不阻断)。
    """

    description: str = Field(description="分镜内容描述")
    shot_type: str | None = Field(
        default=None, description="景别(wide/medium/close/extreme_close 之一)"
    )
    scene: str | None = Field(default=None, description="所在场景")
    plot_point: str | None = Field(default=None, description="剧情节拍/情绪点")
    appearing: list[str] = Field(
        default_factory=list, description="出场角色名清单(从已知角色选,D13)"
    )
    dialogue: str | None = Field(default=None, description="对白文本")
    target_duration: float | None = Field(
        default=None, description="目标时长(秒,3–15;模型未能估算则省略)"
    )
    camera_move: str | None = Field(default=None, description="镜头运动(推/拉/摇/移 等)")
    related_plotline: str | None = Field(default=None, description="关联情节线名(可追溯)")
    related_conflict: str | None = Field(default=None, description="关联冲突名(可追溯)")


class ShotsResult(_Loose):
    shots: list[ShotDraft] = Field(default_factory=list)


class OptimizeResult(_Loose):
    """AI 优化(copy-edit)输出(D12):仅润色后的剧本正文,整版采纳。"""

    content: str = Field(description="copy-edit 后的完整剧本正文(不重排/不改动结构)")
