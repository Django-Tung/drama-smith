"""剧目用例编排(CRUD,事务边界在此,`design.md` D1/D14)。

每个用例调 repo(只 `flush`)+ `commit`;归属经 repo 强制 `user_id` 过滤(越权 / 已删 →
`NotFound`,不泄露存在)。不写裸 SQL;软删经 `deleted_at`,子资源查询自然排除。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.db.models import Drama
from drama_smith.db.repositories import drama_repo


async def list_dramas(session: AsyncSession, user_id: int) -> list[Drama]:
    """列当前用户的剧目(排除软删,按 `sort_order`、`id`)。"""
    return await drama_repo.list_dramas(session, user_id)


async def get_drama(session: AsyncSession, user_id: int, drama_id: int) -> Drama:
    """取单剧(强制 `user_id`;越权 / 不存在 / 已删 → `NotFound`)。"""
    return await drama_repo.get(session, user_id, drama_id)


async def create_drama(session: AsyncSession, user_id: int, *, name: str) -> Drama:
    """建剧;`sort_order` 接当前最大 +1(空则 0),保持列表尾部追加。"""
    existing = await drama_repo.list_dramas(session, user_id)
    sort_order = max((d.sort_order for d in existing), default=-1) + 1
    drama = await drama_repo.create(session, user_id, name=name, sort_order=sort_order)
    await session.commit()
    return drama


async def rename_drama(session: AsyncSession, user_id: int, drama_id: int, *, name: str) -> Drama:
    """重命名(归属经 `get` 校验)。"""
    drama = await drama_repo.get(session, user_id, drama_id)
    renamed = await drama_repo.rename(session, drama, name=name)
    await session.commit()
    return renamed


async def delete_drama(session: AsyncSession, user_id: int, drama_id: int) -> None:
    """软删(子资源经归属链自然隐藏;归属经 `get` 校验)。"""
    drama = await drama_repo.get(session, user_id, drama_id)
    await drama_repo.soft_delete(session, drama)
    await session.commit()
