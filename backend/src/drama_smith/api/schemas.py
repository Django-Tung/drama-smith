"""接口层 pydantic 契约:请求体、响应数据、统一成功 / 错误信封。

成功响应统一 `{data, meta}`(`architecture §3.2`);错误响应统一 `{error: {code, message, details}}`
(见 `core/errors`)。字段 `description` 即 Swagger 文档来源。
校验规则对齐 spec「User Registration」(用户名 3–32 位字母/数字/下划线;密码 ≥8 含字母+数字)。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
            "机器可读错误码:`unauthenticated` / `validation_error` / "
            "`not_found` / `conflict` / `locked` / `internal_error`"
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
    """对外用户信息;`text_model_configured` 本期恒为 false(模型配置属后续里程碑)。"""

    id: int = Field(description="用户 ID(BIGINT UNSIGNED)")
    username: str = Field(description="用户名")
    text_model_configured: bool = Field(
        default=False, description="是否已配置文本模型(本期恒为 false)"
    )
