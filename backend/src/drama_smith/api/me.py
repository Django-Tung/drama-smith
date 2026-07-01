"""当前用户端点 `GET /api/me`。

需鉴权(`get_current_user`);返回 id / username 及配置完成度占位
(`text_model_configured` 本期恒为 false,模型配置属后续里程碑)。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from drama_smith.api.deps import get_current_user
from drama_smith.api.schemas import Envelope, ErrorResponse, UserPublic
from drama_smith.db.models import User

router = APIRouter(tags=["users"])


@router.get(
    "/me",
    summary="获取当前用户",
    description="返回已认证用户的 id、用户名,及文本模型配置完成度(本期恒为 false)。",
    response_model=Envelope[UserPublic],
    responses={
        401: {
            "model": ErrorResponse,
            "description": "未携带或携带无效 / 过期 access 令牌(unauthenticated)",
        }
    },
)
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> Envelope[UserPublic]:
    return Envelope(data=UserPublic(id=current_user.id, username=current_user.username))
