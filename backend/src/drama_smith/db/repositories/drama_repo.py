"""剧仓储。

事务边界在 services 层(M0 D14):本层只查询 / `add` / `flush`,不 commit。
剧直接归属用户,所有读写带 `user_id`(M0 D6 隔离);软删(`deleted_at`),
列表 / 详情默认排除已删(越权或已删 → `NotFound`,不泄露存在性)。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import NotFound
from drama_smith.db.base import utcnow
from drama_smith.db.models import Drama


async def list_dramas(
    session: AsyncSession, user_id: int, *, include_deleted: bool = False
) -> list[Drama]:
    """列当前用户的剧;默认排除软删,按 `sort_order`、`id` 排序。"""
    stmt = select(Drama).where(Drama.user_id == user_id)
    if not include_deleted:
        stmt = stmt.where(Drama.deleted_at.is_(None))
    stmt = stmt.order_by(Drama.sort_order, Drama.id)
    return list((await session.execute(stmt)).scalars().all())


async def get(session: AsyncSession, user_id: int, drama_id: int) -> Drama:
    """按 id 取剧(强制 `user_id` + 排除软删);无命中 / 越权 → `NotFound`。"""
    stmt = select(Drama).where(
        Drama.id == drama_id,
        Drama.user_id == user_id,
        Drama.deleted_at.is_(None),
    )
    drama: Drama | None = (await session.execute(stmt)).scalar_one_or_none()
    if drama is None:
        raise NotFound("Drama not found")
    return drama


async def create(
    session: AsyncSession, user_id: int, *, name: str, sort_order: int = 0
) -> Drama:
    """新建剧。"""
    drama = Drama(user_id=user_id, name=name, sort_order=sort_order)
    session.add(drama)
    await session.flush()
    await session.refresh(drama)  # 回读 server_default
    return drama


async def rename(session: AsyncSession, drama: Drama, *, name: str) -> Drama:
    """重命名已加载的剧(归属已由 `get` 校验)。"""
    drama.name = name
    await session.flush()
    return drama


async def soft_delete(session: AsyncSession, drama: Drama) -> None:
    """软删:置 `deleted_at`(物理行保留,可清理入口独立处理,见 database §5)。"""
    drama.deleted_at = utcnow()
    await session.flush()
