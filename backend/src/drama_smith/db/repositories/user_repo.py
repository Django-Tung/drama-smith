"""用户仓储。

事务边界在 services 层(`design.md` D14):本层只 `add` / `flush` / 查询,不 commit / rollback。
`create` 内 `flush` 以在调用点即时暴露唯一约束冲突 → 映射为 `Conflict`。

用户表的查询语义区别于「按 `user_id` 归属的业务资源」:
- `get_by_username`:登录路径用,无命中返回 `None`(→ 上层按无效凭证 401 处理,不泄露存在性)。
- `get_by_id`:鉴权依赖取「令牌主体」用,无命中返回 `None`(→ 上层 `Unauthenticated`)。
按 `user_id` 强制过滤的多租户范式在 `refresh_token_repo` 落地(`design.md` D6),后续业务表照搬。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import Conflict
from drama_smith.db.models import User


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    """按主键取用户(鉴权依赖用);无命中返回 `None`。"""
    user: User | None = await session.get(User, user_id)
    return user


async def get_by_username(session: AsyncSession, username: str) -> User | None:
    """按用户名取用户(登录路径用);无命中返回 `None`(→ 401,不泄露存在性)。"""
    stmt = select(User).where(User.username == username)
    result = await session.execute(stmt)
    user: User | None = result.scalar_one_or_none()
    return user


async def create(session: AsyncSession, *, username: str, password_hash: str) -> User:
    """创建用户(argon2id 哈希由上层 `core.security` 产出)。

    `flush` 即时触发 `username` 唯一约束,冲突 → `Conflict`;持久化由 services 层 commit。
    """
    user = User(username=username, password_hash=password_hash)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        # `users.username` 为唯一约束;完整性错误即用户名已占用。
        raise Conflict("Username already exists") from exc
    await session.refresh(user)  # 回读 server_default(created_at / updated_at)
    return user
