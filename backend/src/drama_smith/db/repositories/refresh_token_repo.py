"""刷新令牌仓储 —— 多租户隔离范式的验证载体(`design.md` D6)。

按 `user_id` 归属的资源访问一律带 `user_id` 过滤、无命中 → `NotFound`(不泄露存在性);
后续业务表照搬此范式。刷新令牌按其「哈希」寻址(明文即凭证),故归属过滤形态为
`WHERE token_hash=:h AND user_id=:uid`(与 id 寻址资源的 `WHERE id=:id AND user_id=:uid`
等价,均为「按拥有者收窄 + 缺失即 404」)。

方法:
- `get_by_hash`:刷新端点用,按哈希(凭证)查找 —— 此时尚未确定用户,故不做 `user_id`
  过滤,无命中返回 `None`(→ 上层 401)。
- `get_for_user_by_hash`:登出用,强制按 `user_id` 归属过滤 —— 他人令牌亦返回 `NotFound`
  (→ 404,不泄露存在性)。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import NotFound
from drama_smith.db.base import utcnow
from drama_smith.db.models import RefreshToken


async def get_by_hash(session: AsyncSession, token_hash: str) -> RefreshToken | None:
    """按哈希取令牌(刷新端点用);无命中返回 `None`(→ 401)。"""
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    result = await session.execute(stmt)
    token: RefreshToken | None = result.scalar_one_or_none()
    return token


async def get_for_user_by_hash(
    session: AsyncSession, *, user_id: int, token_hash: str
) -> RefreshToken:
    """按哈希取令牌并强制归属用户过滤(登出用)。

    无命中(令牌不存在或不属于该用户)→ `NotFound`,统一 404 不泄露存在性。
    """
    stmt = select(RefreshToken).where(
        RefreshToken.token_hash == token_hash,
        RefreshToken.user_id == user_id,
    )
    result = await session.execute(stmt)
    token: RefreshToken | None = result.scalar_one_or_none()
    if token is None:
        raise NotFound("Refresh token not found")
    return token


async def create(
    session: AsyncSession,
    *,
    user_id: int,
    token_hash: str,
    expires_at: datetime,
) -> RefreshToken:
    """持久化刷新令牌(仅哈希,明文永不落库)。`flush` 暴露约束冲突。"""
    token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(token)
    await session.flush()
    return token


async def revoke(session: AsyncSession, token: RefreshToken) -> None:
    """吊销令牌(置 `revoked_at` = 当前 UTC);持久化由 services 层 commit。"""
    token.revoked_at = utcnow()
    await session.flush()
