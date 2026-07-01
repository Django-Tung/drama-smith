"""接口层依赖:OAuth2 Bearer、Security 薄适配、当前用户。

设计依据(`design.md` D15 / D18、`backend.md` §4):
- `Security` 为薄适配:读 settings 后把 `secret` / `ttl` 显式传入 `core.security` 原语;
  验签失败(pyjwt 原生异常)在此映射为 `Unauthenticated`(401),原语保持纯粹。
- `get_current_user`:取 Bearer token → 验签 → 取用户 → 校验未锁定(锁定 → `Locked`)。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.config import get_settings
from drama_smith.core.errors import Locked, Unauthenticated
from drama_smith.core.security import create_access_token, verify_access_token
from drama_smith.db.base import utcnow
from drama_smith.db.models import User
from drama_smith.db.repositories import user_repo
from drama_smith.db.session import get_session

# `tokenUrl` 仅用于 OpenAPI / Swagger「Authorize」表单展示;实际登录端点接收 JSON。
oauth_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


@dataclass(frozen=True)
class Security:
    """`core.security` 原语与 settings 之间的薄适配(便于阶段六单测注入)。"""

    secret: str
    access_ttl_seconds: int

    def issue_access_token(self, user_id: int, username: str) -> str:
        return create_access_token(user_id, username, self.secret, self.access_ttl_seconds)

    def verify_access_token(self, token: str) -> Mapping[str, Any]:
        try:
            return verify_access_token(token, self.secret)
        except jwt.PyJWTError as exc:
            # 过期 / 签名错误 / 格式错误等一律视为未认证(→ 401),不细分以收敛信息面。
            raise Unauthenticated("Invalid or expired access token") from exc


def get_security() -> Security:
    """FastAPI 依赖:按当前 settings 构造 `Security`(支持测试期 `override_settings`)。"""
    settings = get_settings()
    return Security(
        secret=settings.jwt_secret.get_secret_value(),
        access_ttl_seconds=settings.jwt_access_ttl_seconds,
    )


async def get_current_user(
    token: Annotated[str, Depends(oauth_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
    sec: Annotated[Security, Depends(get_security)],
) -> User:
    """解析 Bearer token 并返回已认证、未锁定的用户。

    - 无 / 坏 / 过期令牌:OAuth2 scheme 抛 401,或 `verify_access_token` 抛 `Unauthenticated`。
    - 令牌主体已不存在(如用户被删):视为未认证,迫使重新登录(`Unauthenticated`)。
    - 账号被锁定:`Locked`(423)。
    """
    claims = sec.verify_access_token(token)
    user = await user_repo.get_by_id(session, int(claims["sub"]))
    if user is None:
        raise Unauthenticated("Authentication required")
    if user.locked_until is not None and user.locked_until > utcnow():
        raise Locked("Account is locked")
    return user
