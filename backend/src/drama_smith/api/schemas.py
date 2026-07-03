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
    """对外用户信息;`text_model_configured` 反映是否存在 active 文本配置(门禁信号,D9)。"""

    id: int = Field(description="用户 ID(BIGINT UNSIGNED)")
    username: str = Field(description="用户名")
    text_model_configured: bool = Field(
        default=False, description="是否已配置 active 文本模型(前端据此路由向导)"
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
