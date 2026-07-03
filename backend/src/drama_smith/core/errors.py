"""统一错误处理:领域异常 + 全局异常处理器。

错误响应统一格式(`architecture §3.2` / `design.md` D7)::

    {"error": {"code": "<machine_code>", "message": "<人类可读>", "details": {...}}}

HTTP 状态码与 `code` 对齐。本期落地的 `code`:`unauthenticated` / `validation_error` /
`not_found` / `conflict` / `locked` / `internal_error`。

分层(`design.md` D15):领域异常由 services / deps / repos 抛出;`core/security` 保持
纯原语,不在内部 import 本模块 —— 验签失败(pyjwt 原生异常)由 `api/deps` 映射为
`Unauthenticated`。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("drama_smith.errors")

# 错误体 `details` 字段的类型。
Details = dict[str, Any]


class DomainError(Exception):
    """所有领域异常基类;子类声明 `code` / `status_code` / `default_message`。

    抛出时可覆盖 `message`、附带 `details`;处理器据 `code` / `status_code` 出统一格式。
    """

    code: str = "internal_error"
    status_code: int = 500
    default_message: str = "Internal server error"

    def __init__(self, message: str | None = None, *, details: Details | None = None) -> None:
        self.message = message if message is not None else self.default_message
        self.details: Details = details if details is not None else {}
        super().__init__(self.message)


class Unauthenticated(DomainError):
    """缺少 / 无效 / 过期凭证(401)。"""

    code = "unauthenticated"
    status_code = 401
    default_message = "Authentication required"


class NotFound(DomainError):
    """资源不存在或越权访问他人资源(404,不泄露存在性)。"""

    code = "not_found"
    status_code = 404
    default_message = "Resource not found"


class Conflict(DomainError):
    """资源冲突(如用户名已占用,409)。"""

    code = "conflict"
    status_code = 409
    default_message = "Resource already exists"


class Locked(DomainError):
    """账号因连续登录失败被锁定(423)。"""

    code = "locked"
    status_code = 423
    default_message = "Account is temporarily locked due to repeated failed logins"


class ModelNotConfigured(DomainError):
    """用户尚无 active 文本配置,无法执行依赖模型的操作(409)。

    本期不被任何端点触发(预留);M2 分析 service 经 `require_active_text` 调用。
    """

    code = "model_not_configured"
    status_code = 409
    default_message = "No active text model configuration; please configure one first"


class ProviderAuthFailed(DomainError):
    """供应商鉴权失败(401/403):API Key 无效或已失效(502,并置 `status=invalid`)。"""

    code = "provider_auth_failed"
    status_code = 502
    default_message = "Provider rejected the API key (authentication failed)"


class RateLimited(DomainError):
    """供应商限流 / 超时,有限重试后仍失败(provider 429 / timeout → 502)。"""

    code = "rate_limited"
    status_code = 502
    default_message = "Provider rate-limited or timed out"


class QuotaExceeded(DomainError):
    """用户并发 / 配额超限(429;执行器配额门,M2+ 触发,本期仅定义)。"""

    code = "quota_exceeded"
    status_code = 429
    default_message = "Concurrency or quota limit reached"


# HTTP 状态 → 错误码兜底映射。主要服务 FastAPI/Starlette 自身抛出的 `HTTPException`,
# 例如 OAuth2 缺失令牌的 401、未匹配路由的 404;未列出的 5xx 归 `internal_error`。
_STATUS_TO_CODE: dict[int, str] = {
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    423: "locked",
    429: "rate_limited",
    500: "internal_error",
    502: "bad_gateway",
    503: "service_unavailable",
    504: "gateway_timeout",
}


def _error_body(code: str, message: str, details: Details) -> dict[str, Any]:
    """构造统一错误响应体。"""
    return {"error": {"code": code, "message": message, "details": details}}


async def _domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(exc.code, exc.message, exc.details),
    )


async def _validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_error_body(
            "validation_error",
            "Request validation failed",
            {"errors": jsonable_encoder(exc.errors())},
        ),
    )


async def _http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _STATUS_TO_CODE.get(
        exc.status_code, "internal_error" if exc.status_code >= 500 else "error"
    )
    detail = exc.detail
    if isinstance(detail, str):
        message: str = detail
        details: Details = {}
    else:
        # `detail` 可能为 dict / 列表等结构化对象;归入 details,不复用为顶层 message。
        message = "Request error"
        details = {"detail": jsonable_encoder(detail)}
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(code, message, details),
        headers=getattr(exc, "headers", None),
    )


async def _unhandled_exception_handler(request: Request, _exc: Exception) -> JSONResponse:
    # 服务端记录完整堆栈(脱敏见 `architecture §5.4`);响应仅返回通用文案,不泄露内部。
    logger.exception("Unhandled exception during %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=_error_body("internal_error", "Internal server error", {}),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI 应用上注册统一异常处理器,覆盖默认的 HTTP/校验错误响应格式。

    `ExceptionMiddleware` 按 MRO 最具体类型匹配:领域异常、校验异常优先于 `HTTPException`,
    后者优先于兜底的 `Exception`。故注册顺序不影响最终匹配。

    注:Starlette 的 `add_exception_handler` 期望 `(Request, Exception)` 处理器签名,
    而此处各处理器为可读性按具体异常类型标注 —— 运行时 Starlette 仅传入匹配类型,
    逐行 `type: ignore[arg-type]` 抑制 mypy 的参数逆变告警(本仓库既定惯例)。
    """
    app.add_exception_handler(DomainError, _domain_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error_handler)  # type: ignore[arg-type]
    # 同时覆盖 Starlette 与 FastAPI 的 `HTTPException`(后者为前者子类;FastAPI 默认在
    # 子类上注册,故需显式覆盖以统一 OAuth2 缺失令牌的 401 等响应格式)。
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_exception_handler)


__all__ = [
    "Conflict",
    "DomainError",
    "Locked",
    "ModelNotConfigured",
    "NotFound",
    "ProviderAuthFailed",
    "QuotaExceeded",
    "RateLimited",
    "Unauthenticated",
    "register_exception_handlers",
]
