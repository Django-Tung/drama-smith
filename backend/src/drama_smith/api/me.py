"""当前用户端点 `GET /api/me`。

需鉴权(`get_current_user`);返回 id / username 及文本模型配置完成度
(`text_model_configured` = 是否存在 active 文本配置,前端门禁信号,design D9)。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.api.deps import get_current_user
from drama_smith.api.schemas import Envelope, ErrorResponse, UserPublic
from drama_smith.db.models import User
from drama_smith.db.session import get_session
from drama_smith.services import model_config_service

router = APIRouter(tags=["users"])


@router.get(
    "/me",
    summary="获取当前用户",
    description=(
        "返回已认证用户的 id、用户名,及文本模型配置完成度"
        "(`text_model_configured`:是否存在 active 文本配置,前端据此路由向导)。"
    ),
    response_model=Envelope[UserPublic],
    responses={
        401: {
            "model": ErrorResponse,
            "description": "未携带或携带无效 / 过期 access 令牌(unauthenticated)",
        }
    },
)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Envelope[UserPublic]:
    configured = await model_config_service.has_text_configured(session, current_user.id)
    return Envelope(
        data=UserPublic(
            id=current_user.id,
            username=current_user.username,
            text_model_configured=configured,
        )
    )
