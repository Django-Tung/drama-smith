"""接口层 pydantic 契约:请求体、响应数据、统一成功 / 错误信封。

成功响应统一 `{data, meta}`(`architecture §3.2`);错误响应统一 `{error: {code, message, details}}`
(见 `core/errors`)。字段 `description` 即 Swagger 文档来源。
校验规则对齐 spec「User Registration」(用户名 3–32 位字母/数字/下划线;密码 ≥8 含字母+数字)。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from drama_smith.llm import validate_provider

# 用户名:3–32 位,字母 / 数字 / 下划线。
_USERNAME_PATTERN = r"^[A-Za-z0-9_]+$"


class Envelope[T](BaseModel):
    """统一成功响应信封(`{data, meta}`)。"""

    data: T = Field(description="业务数据负载")
    meta: dict[str, Any] = Field(
        default_factory=dict,
        description="分页 / 额外元信息;非列表端点一般为空对象",
    )


class ErrorDetail(BaseModel):
    """单条错误信息。"""

    code: str = Field(
        description=(
            "机器可读错误码:`unauthenticated` / `validation_error` / `not_found` / "
            "`conflict` / `locked` / `model_not_configured` / `provider_auth_failed` / "
            "`rate_limited` / `quota_exceeded` / `internal_error`"
        )
    )
    message: str = Field(description="人类可读的错误说明")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="结构化补充信息;校验错误为 `{errors: [...]}`",
    )


class ErrorResponse(BaseModel):
    """统一错误响应体(`{error: {code, message, details}}`)。"""

    error: ErrorDetail = Field(description="错误详情")


class RegisterRequest(BaseModel):
    """注册请求。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=3,
        max_length=32,
        pattern=_USERNAME_PATTERN,
        description="用户名:3–32 位,仅字母 / 数字 / 下划线,系统内唯一",
        examples=["alice_01"],
    )
    password: str = Field(
        min_length=8,
        max_length=128,
        description="密码:8–128 位,需同时包含字母与数字(明文仅用于本次校验,以 argon2id 哈希落库)",
        examples=["alicePass123"],
    )

    @field_validator("password")
    @classmethod
    def _password_has_letter_and_digit(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value) or not re.search(r"[0-9]", value):
            msg = "password must contain both letters and digits"
            raise ValueError(msg)
        return value


class LoginRequest(BaseModel):
    """登录请求。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=32, description="用户名")
    password: str = Field(
        min_length=1, max_length=128, description="明文密码(仅用于本次校验,不落库 / 不记日志)"
    )


class RefreshRequest(BaseModel):
    """刷新请求。"""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(
        min_length=1, description="不透明刷新令牌(注册 / 登录时下发)", examples=["<refresh_token>"]
    )


class LogoutRequest(BaseModel):
    """登出请求。"""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(
        min_length=1, description="待吊销的刷新令牌,须属于当前用户", examples=["<refresh_token>"]
    )


class TokenData(BaseModel):
    """注册 / 登录返回:access + refresh 令牌。"""

    access_token: str = Field(
        description=(
            "HS256 JWT 访问令牌(默认 15 分钟有效);"
            "放入 `Authorization: Bearer <access_token>` 请求头"
        )
    )
    refresh_token: str = Field(
        description="不透明刷新令牌(7 天有效),用于换取新 access;仅下发一次,服务端只存哈希"
    )
    token_type: str = Field(default="Bearer", description="令牌类型")  # noqa: S105


class AccessTokenData(BaseModel):
    """刷新端点返回:仅新 access 令牌(spec 不轮换 refresh)。"""

    access_token: str = Field(description="新签发的 HS256 JWT 访问令牌")
    token_type: str = Field(default="Bearer", description="令牌类型")  # noqa: S105


class UserPublic(BaseModel):
    """对外用户信息;`*_model_configured` 反映是否存在 active 文本/图片配置(门禁信号,D9)。"""

    id: int = Field(description="用户 ID(BIGINT UNSIGNED)")
    username: str = Field(description="用户名")
    text_model_configured: bool = Field(
        default=False, description="是否已配置 active 文本模型(前端据此路由向导)"
    )
    image_model_configured: bool = Field(
        default=False, description="是否已配置 active 图片模型(前端形象图门禁信号)"
    )


# ---- BYOK 模型配置契约(api/models)----
# 供应商白名单按 purpose 校验(D12):越界 (purpose, provider) → 422 validation_error。


class ModelConfigCreate(BaseModel):
    """新建模型配置请求。明文 `api_key` 仅用于本次信封加密,永不落库 / 日志 / 响应。"""

    model_config = ConfigDict(extra="forbid")

    purpose: Literal["text", "image", "video"] = Field(
        description="用途;text 为必配(前端门禁),image / video 可选"
    )
    provider: str = Field(min_length=1, max_length=64, description="供应商;须在 purpose 白名单内")
    model: str = Field(
        min_length=1, max_length=128, description="模型标识(供应商特定,如 gpt-4o-mini)"
    )
    api_key: str = Field(
        min_length=1,
        max_length=512,
        description="明文 API Key;仅本次信封加密,响应只回脱敏串",
    )
    base_url: str | None = Field(
        default=None, max_length=512, description="OpenAI 兼容 base_url;缺省用 provider 默认"
    )
    params: dict[str, Any] | None = Field(default=None, description="调用参数(temperature 等)")
    provider_options: dict[str, Any] | None = Field(default=None, description="供应商专属选项")

    @model_validator(mode="after")
    def _provider_on_whitelist(self) -> ModelConfigCreate:
        validate_provider(self.purpose, self.provider)
        return self


class ModelConfigUpdate(BaseModel):
    """更新模型配置请求(PUT)。`api_key` 缺省 / null → 不动加密列(D8)。

    `purpose` 不可改(语义不变);改 `provider` 时由 service 按既有 purpose 复校白名单。
    """

    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, min_length=1, max_length=64)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        description="给出则全量重封;缺省 / null 不动加密列",
    )
    params: dict[str, Any] | None = Field(default=None)
    provider_options: dict[str, Any] | None = Field(default=None)


class ModelConfigPublic(BaseModel):
    """模型配置对外视图;仅脱敏 key(`api_key_masked`),明文 / 密文永不出现。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="配置 ID")
    purpose: str
    provider: str
    model: str
    base_url: str | None
    api_key_masked: str = Field(description="脱敏 API Key(前 3 … 后 4),仅供辨认")
    params: dict[str, Any] | None
    provider_options: dict[str, Any] | None
    is_active: bool = Field(description="是否当前 purpose 的生效配置")
    status: str = Field(description="active / invalid(自检鉴权失败置 invalid)")
    last_tested_at: datetime | None = Field(default=None, description="最近一次零成本自检时间")


# ---- M2 结构化分析契约(api: dramas / episodes / script / characters / analysis /
# shots / tasks)----
# 响应 Public 用 `from_attributes=True`(经 `model_validate(orm)` 读 ORM 行);请求体一律
# `extra="forbid"`(未知键 422,防误传)。`Envelope[T]` 信封统一包裹;错误抛 `DomainError`
# 子类由全局处理器映射(`{error:{code,message,details}}`),路由内不写 try/except。


AspectRatio = Literal["16:9", "9:16", "1:1", "4:3"]
ScriptFormat = Literal["plain", "markdown", "fountain"]
ShotType = Literal["wide", "medium", "close", "extreme_close"]
EpisodeStatus = Literal["draft", "analyzing", "ready", "rendering", "done"]


class DramaPublic(BaseModel):
    """剧目对外视图。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class EpisodePublic(BaseModel):
    """剧集对外视图。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    drama_id: int
    title: str
    sort_order: int
    aspect_ratio: str
    style_preset: str | None
    status: str
    current_analysis_id: int | None = Field(description="当前生效分析指针(NULL=未拆解)")
    created_at: datetime
    updated_at: datetime


class ScriptPublic(BaseModel):
    """剧本容器对外视图(与剧集 1:1,持当前版本指针)。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    episode_id: int
    current_version_id: int | None = Field(description="当前生效版本指针(NULL=无剧本)")


class ScriptVersionPublic(BaseModel):
    """剧本版本对外视图(不可变追加;`source` ∈ input/optimize)。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    script_id: int
    version_no: int
    content: str
    format: str
    source: str
    created_at: datetime


class EpisodeCharacterPublic(BaseModel):
    """剧集角色对外视图(preset / analysis 两源)。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    episode_id: int
    name: str
    role_type: str | None
    persona: str | None
    motivation: str | None
    traits: list[str] | None
    appearance_desc: str | None
    image_media_id: int | None = Field(
        default=None, description="当前形象图指针(NULL=无形象图;逻辑指针,无 FK,M3)"
    )
    source: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class MediaPublic(BaseModel):
    """富媒体对外视图(media 元数据 + 短期签名 URL;本期 `kind='image'` 形象图)。

    由 service 的 `_portrait_view` dict 构造(非 ORM 行),含 `<img src>` 直用的签名 URL;
    `content_type`/尺寸供前端预判渲染,`source` ∈ upload/generate。
    """

    media_id: int = Field(description="media ID(BIGINT UNSIGNED)")
    signed_url: str = Field(description="内容端点相对 URL(`<img src>` 直用;含短期 token)")
    content_type: str | None = Field(default=None, description="MIME(如 image/jpeg)")
    width: int | None = Field(default=None, description="像素宽")
    height: int | None = Field(default=None, description="像素高")
    source: str = Field(description="来源:upload / generate")
    created_at: datetime = Field(description="落库时间(UTC,毫秒精度)")


class AnalysisPublic(BaseModel):
    """分析产物对外视图(四维 result + 配置快照,append-only)。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    episode_id: int
    status: str
    result: dict[str, Any] | None
    config_snapshot: dict[str, Any] | None
    script_version_id: int
    created_at: datetime
    updated_at: datetime


class TaskPublic(BaseModel):
    """任务对外视图(进度 / 状态 / 错误 / 产物引用)。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    episode_id: int | None
    type: str
    status: str
    progress: int
    stage: str | None
    trigger: str
    input_snapshot: dict[str, Any] | None
    output_refs: dict[str, Any] | None = Field(
        default=None,
        description="成功产物引用(analyze→analysis_id;optimize→version_id+diff)",
    )
    error: dict[str, Any] | None = Field(default=None, description="失败原因体({code,message})")
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class AnalysisSummary(BaseModel):
    """`GET /episodes/:id/analysis` 双语义读(D11):上次结果 + 在途任务 + 过期标记。"""

    current_analysis: AnalysisPublic | None = Field(
        default=None, description="current 指针的分析(含 result)或 None"
    )
    inflight_task: TaskPublic | None = Field(
        default=None, description="该剧集在途 analyze 任务(pending/running)或 None"
    )
    stale_flag: bool = Field(
        default=False, description="current 所基于版本 ≠ 当前剧本版本(提示重拆,不阻断)"
    )


class ShotAppearRef(BaseModel):
    """分镜出场角色引用(角色 id + 名 + 该镜内作用)。"""

    episode_character_id: int
    name: str
    role_in_shot: str | None = None


class ShotPublic(BaseModel):
    """分镜对外视图;`appearing` 由 API 层按出场关联回填(非 ORM 列)。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_id: int
    episode_id: int
    seq: int
    description: str
    shot_type: str | None
    scene: str | None
    plot_point: str | None
    dialogue: str | None
    target_duration: float | None
    camera_move: str | None
    related_plotline: str | None
    related_conflict: str | None
    appearing: list[ShotAppearRef] = Field(
        default_factory=list, description="该镜出场角色(经 shot_characters 回填)"
    )


class ShotWarning(BaseModel):
    """`target_duration` 越界标注(D5,软校验不阻断保存)。"""

    shot_id: int
    target_duration: float
    issue: Literal["too_short", "too_long"]


class ShotEditResult(BaseModel):
    """patch / split / merge 结果:操作后的镜(含出场)+ 越界标注。"""

    shot: ShotPublic
    warnings: list[ShotWarning] = Field(default_factory=list)


# ---- 请求体(均 `extra="forbid"`;未知键 422)----


class DramaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128, description="剧目名")


class DramaRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128, description="新剧目名")


class EpisodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=128)
    aspect_ratio: AspectRatio
    style_preset: str | None = Field(default=None, max_length=64)


class EpisodeUpdate(BaseModel):
    """剧集更新(全可选);缺省字段不改、显式 null 清空 `style_preset`。"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=128)
    aspect_ratio: AspectRatio | None = None
    style_preset: str | None = Field(default=None, max_length=64)
    status: EpisodeStatus | None = None


class ScriptUpsert(BaseModel):
    """写入剧本正文(产 `source='input'` 版本并移 current 指针)。"""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, description="剧本正文(MEDIUMTEXT)")
    format: ScriptFormat = Field(default="markdown")


class CharacterCreate(BaseModel):
    """新建预置角色(`source='preset'`)。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    role_type: str | None = Field(default=None, max_length=32)
    persona: str | None = Field(default=None, max_length=512)
    motivation: str | None = Field(default=None, max_length=512)
    traits: list[str] | None = None
    appearance_desc: str | None = Field(default=None, max_length=1024)
    sort_order: int = Field(default=0)


class CharacterUpdate(BaseModel):
    """更新角色(全可选;`model_fields_set` 转发,缺省不改、null 清空可空字段)。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=64)
    role_type: str | None = Field(default=None, max_length=32)
    persona: str | None = Field(default=None, max_length=512)
    motivation: str | None = Field(default=None, max_length=512)
    traits: list[str] | None = None
    appearance_desc: str | None = Field(default=None, max_length=1024)
    sort_order: int | None = None


class AnalysisCurrentPatch(BaseModel):
    """切换当前分析指针(D11;analysis 须属本剧集)。"""

    model_config = ConfigDict(extra="forbid")

    analysis_id: int


class ShotPatch(BaseModel):
    """分镜字段更新(全可选);`appearing` 给出则全量替换出场角色。"""

    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=1024)
    shot_type: ShotType | None = None
    scene: str | None = Field(default=None, max_length=128)
    plot_point: str | None = Field(default=None, max_length=255)
    dialogue: str | None = None
    target_duration: float | None = Field(default=None, ge=0)
    camera_move: str | None = Field(default=None, max_length=64)
    related_plotline: str | None = Field(default=None, max_length=128)
    related_conflict: str | None = Field(default=None, max_length=128)
    appearing: list[int] | None = Field(
        default=None, description="给出则全量替换出场角色(episode_character_id 列表)"
    )


class ShotSplit(BaseModel):
    """在某镜后插入新镜;`description` 必填(分镜 NOT NULL),其余可选。"""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=1024)
    shot_type: ShotType | None = None
    scene: str | None = Field(default=None, max_length=128)
    plot_point: str | None = Field(default=None, max_length=255)
    dialogue: str | None = None
    target_duration: float | None = Field(default=None, ge=0)
    camera_move: str | None = Field(default=None, max_length=64)
    related_plotline: str | None = Field(default=None, max_length=128)
    related_conflict: str | None = Field(default=None, max_length=128)
    appearing: list[int] | None = Field(
        default=None, description="新镜出场角色(episode_character_id 列表)"
    )


class ShotMerge(BaseModel):
    """合并 `shot_id` 到 `into_shot_id`(须同 analysis)。"""

    model_config = ConfigDict(extra="forbid")

    into_shot_id: int


class ShotsReorder(BaseModel):
    """重排 current_analysis 名下分镜(须恰好覆盖其全部镜 id)。"""

    model_config = ConfigDict(extra="forbid")

    ordered_ids: list[int] = Field(min_length=1)
