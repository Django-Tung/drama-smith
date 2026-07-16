"""富媒体元数据仓储(`media` 表;M3)。

事务边界在 services 层(M0 D14):本层只查询 / `add` / `flush`,不 commit。所有读写带
`user_id` 强制过滤(越权 → `NotFound`,不泄露存在)。多态归属经 `(owner_type, owner_id)`。

`create` 在插入选中行(`selected=True`)前,先把同 `(user_id, owner_type, owner_id)` 的旧行
翻 `selected=False`——既实现「同 owner 恰一条 selected」(D9 单选),也避免 `UNIQUE(selected_key)`
冲突(两 selected 行产同 key)。DB 生成列约束为竞态兜底。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import NotFound
from drama_smith.db.models import Media


async def create(
    session: AsyncSession,
    user_id: int,
    *,
    kind: str,
    owner_type: str,
    owner_id: int,
    source: str,
    storage_key: str,
    content_type: str,
    size_bytes: int,
    width: int | None = None,
    height: int | None = None,
    duration_sec: float | None = None,
    selected: bool = True,
    storage_provider: str = "local",
    extra: dict[str, Any] | None = None,
    provider_task: str | None = None,
) -> Media:
    """新建 media 行;`selected=True`(默认)时先翻同 owner 旧行为 False,再插入。

    本期 `kind='image'` / `owner_type='character'`;`storage_provider` 固定 `'local'`
    (`storage_key` 为 `FileStore` 相对路径)。`flush` 触发生成列 + server_default 回读。
    """
    if selected:
        await session.execute(
            sql_update(Media)
            .where(
                Media.user_id == user_id,
                Media.owner_type == owner_type,
                Media.owner_id == owner_id,
                Media.selected.is_(True),
            )
            .values(selected=False)
        )
    media = Media(
        user_id=user_id,
        kind=kind,
        owner_type=owner_type,
        owner_id=owner_id,
        source=source,
        storage_provider=storage_provider,
        storage_key=storage_key,
        content_type=content_type,
        size_bytes=size_bytes,
        width=width,
        height=height,
        duration_sec=duration_sec,
        selected=selected,
        extra=extra,
        provider_task=provider_task,
    )
    session.add(media)
    await session.flush()
    await session.refresh(media)  # 回读 server_default 与生成列
    return media


async def get(session: AsyncSession, user_id: int, media_id: int) -> Media:
    """按 id 取 media(强制 `user_id`);无命中 / 越权 → `NotFound`。"""
    stmt = select(Media).where(Media.id == media_id, Media.user_id == user_id)
    media: Media | None = (await session.execute(stmt)).scalar_one_or_none()
    if media is None:
        raise NotFound("Media not found")
    return media


async def get_current_for_owner(
    session: AsyncSession,
    user_id: int,
    *,
    owner_type: str,
    owner_id: int,
) -> Media | None:
    """取某 owner 当前选用(`selected=True`)的 media;无则 None。本期 owner_type='character'。"""
    stmt = select(Media).where(
        Media.user_id == user_id,
        Media.owner_type == owner_type,
        Media.owner_id == owner_id,
        Media.selected.is_(True),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_by_id(session: AsyncSession, media_id: int) -> Media | None:
    """按 id 取 media(**不**带 `user_id` 过滤);无命中 → None。

    仅供内容端点 `GET /api/media/:id/content` 用:鉴权凭证是签名 token(`FileStore.verify`,
    `sub == media_id` + 未过期),非用户会话——故此处不再按 user 过滤。其它路径应走 `get`。
    """
    stmt = select(Media).where(Media.id == media_id)
    return (await session.execute(stmt)).scalar_one_or_none()
