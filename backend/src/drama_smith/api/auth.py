"""认证端点:`POST /api/auth/{register,login,refresh,logout}`。

接口层只做参数解析与响应组装;用例编排与事务边界在 `services.auth_service`。
`register` / `login` / `refresh` 为公开端点(无需 access token);`logout` 需鉴权
(按当前用户归属吊销其 refresh,复用多租户过滤范式)。

各端点经 `summary` / `description` / `responses` 暴露给 Swagger;错误响应统一引用
`ErrorResponse`(`{error: {code, message, details}}`)。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.api.deps import get_current_user
from drama_smith.api.schemas import (
    AccessTokenData,
    Envelope,
    ErrorResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenData,
)
from drama_smith.core.config import Settings, get_settings
from drama_smith.db.models import User
from drama_smith.db.session import get_session
from drama_smith.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

# 公共错误响应:请求体校验失败(各端点均可能返回)。
_VALIDATION_ERROR: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "请求体校验失败(validation_error)"}
}


@router.post(
    "/register",
    summary="注册新用户",
    description=(
        "创建用户并签发令牌。校验:用户名 3–32 位字母/数字/下划线且系统唯一;"
        "密码 ≥8 位且同时含字母与数字。密码以 argon2id 哈希存储,明文不落库 / 日志。"
        "成功返回 access(HS256 JWT,15min)+ refresh(不透明,7d,仅存哈希)。"
    ),
    response_model=Envelope[TokenData],
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse, "description": "用户名已存在(conflict)"},
        **_VALIDATION_ERROR,
    },
)
async def register(
    body: RegisterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Envelope[TokenData]:
    result = await auth_service.register(
        session, username=body.username, password=body.password, settings=settings
    )
    return Envelope(
        data=TokenData(access_token=result.access_token, refresh_token=result.refresh_token)
    )


@router.post(
    "/login",
    summary="登录",
    description=(
        "校验用户名 + 密码。成功重置失败计数、记录 `last_login_at`,并签发 access + refresh。"
        "失败按账号递增计数;连续 5 次失败锁定 15 分钟(锁定期内即使密码正确也返回 `locked`)。"
        "用户不存在或密码错误均返回 401,不泄露账号是否存在。"
    ),
    response_model=Envelope[TokenData],
    responses={
        401: {"model": ErrorResponse, "description": "用户名或密码错误(unauthenticated)"},
        423: {"model": ErrorResponse, "description": "账号已锁定(locked)"},
        **_VALIDATION_ERROR,
    },
)
async def login(
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Envelope[TokenData]:
    result = await auth_service.login(
        session, username=body.username, password=body.password, settings=settings
    )
    return Envelope(
        data=TokenData(access_token=result.access_token, refresh_token=result.refresh_token)
    )


@router.post(
    "/refresh",
    summary="刷新访问令牌",
    description=(
        "用有效的(未过期、未吊销)refresh 令牌换取新的 access 令牌。"
        "本端点不轮换 refresh 令牌;登出后 refresh 被吊销,无法再刷新。"
    ),
    response_model=Envelope[AccessTokenData],
    responses={
        401: {
            "model": ErrorResponse,
            "description": "refresh 令牌无效 / 过期 / 已吊销(unauthenticated)",
        },
    },
)
async def refresh(
    body: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Envelope[AccessTokenData]:
    access_token = await auth_service.refresh(
        session, refresh_token=body.refresh_token, settings=settings
    )
    return Envelope(data=AccessTokenData(access_token=access_token))


@router.post(
    "/logout",
    summary="登出(吊销 refresh)",
    description=(
        "需携带有效 access 令牌。吊销当前用户的 refresh 令牌(置 `revoked_at`)。"
        "传入的 refresh 必须属于当前用户,否则返回 404(不泄露存在性)。成功无响应体。"
    ),
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {
            "model": ErrorResponse,
            "description": "未携带或携带无效 access 令牌(unauthenticated)",
        },
        404: {
            "model": ErrorResponse,
            "description": "refresh 令牌不属于当前用户(not_found)",
        },
    },
)
async def logout(
    body: LogoutRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    await auth_service.logout(session, user_id=current_user.id, refresh_token=body.refresh_token)
