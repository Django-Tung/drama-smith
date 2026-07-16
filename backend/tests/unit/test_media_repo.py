"""`media_repo` 单元测试:create 单选翻旧(D9 / `selected_key` UNIQUE)+ get / get_current /
get_by_id(内容端点不按 user 过滤)+ 跨用户隔离。

直连测试库会话(`db_session`),不走 HTTP。`owner_id` 无 FK,故用任意 int 模拟角色 id。
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import NotFound
from drama_smith.db.repositories import media_repo as repo
from drama_smith.db.repositories import user_repo


async def _make_user(session: AsyncSession, username: str = "alice") -> int:
    user = await user_repo.create(session, username=username, password_hash="hash")
    return user.id


async def _create(
    session: AsyncSession,
    uid: int,
    *,
    owner_id: int = 100,
    selected: bool = True,
    source: str = "upload",
) -> int:
    media = await repo.create(
        session,
        uid,
        kind="image",
        owner_type="character",
        owner_id=owner_id,
        source=source,
        storage_key=f"{uid}/{owner_id}/x.png",
        content_type="image/png",
        size_bytes=123,
        width=4,
        height=4,
        selected=selected,
    )
    return media.id


class TestCreateAndSingleSelect:
    async def test_first_selected(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        mid = await _create(db_session, uid)
        current = await repo.get_current_for_owner(
            db_session, uid, owner_type="character", owner_id=100
        )
        assert current is not None and current.id == mid and current.selected is True

    async def test_new_selected_deselects_old(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        old = await _create(db_session, uid, owner_id=100)
        new = await _create(db_session, uid, owner_id=100)
        current = await repo.get_current_for_owner(
            db_session, uid, owner_type="character", owner_id=100
        )
        assert current is not None and current.id == new
        # 旧行翻 False 后仍存在(append-only,旧图保留不删,D9)
        old_row = await repo.get(db_session, uid, old)
        assert old_row.selected is False

    async def test_unselected_keeps_current(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        first = await _create(db_session, uid, owner_id=100, selected=True)
        await _create(db_session, uid, owner_id=100, selected=False)
        current = await repo.get_current_for_owner(
            db_session, uid, owner_type="character", owner_id=100
        )
        assert current is not None and current.id == first

    async def test_selects_are_per_owner(self, db_session: AsyncSession) -> None:
        # 不同 owner 各自单选,互不干扰
        uid = await _make_user(db_session)
        a = await _create(db_session, uid, owner_id=100)
        b = await _create(db_session, uid, owner_id=200)
        ca = await repo.get_current_for_owner(
            db_session, uid, owner_type="character", owner_id=100
        )
        cb = await repo.get_current_for_owner(
            db_session, uid, owner_type="character", owner_id=200
        )
        assert ca is not None and ca.id == a
        assert cb is not None and cb.id == b


class TestReads:
    async def test_get_current_none_when_empty(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        assert (
            await repo.get_current_for_owner(
                db_session, uid, owner_type="character", owner_id=999
            )
            is None
        )

    async def test_get_cross_user_not_found(self, db_session: AsyncSession) -> None:
        u1 = await _make_user(db_session, "u1")
        u2 = await _make_user(db_session, "u2")
        mid = await _create(db_session, u1)
        assert await repo.get(db_session, u1, mid) is not None  # type: ignore[truthy-bool]
        with pytest.raises(NotFound):
            await repo.get(db_session, u2, mid)  # 跨用户 → NotFound(不泄露存在)

    async def test_get_current_cross_user_isolated(self, db_session: AsyncSession) -> None:
        u1 = await _make_user(db_session, "u1")
        u2 = await _make_user(db_session, "u2")
        await _create(db_session, u1, owner_id=100)
        # u2 查同一 owner_id → None(各自的 user_id 隔离)
        assert (
            await repo.get_current_for_owner(
                db_session, u2, owner_type="character", owner_id=100
            )
            is None
        )

    async def test_get_by_id_ignores_user(self, db_session: AsyncSession) -> None:
        # 内容端点鉴权凭证是签名 token(非用户会话)→ get_by_id 不按 user 过滤
        uid = await _make_user(db_session)
        mid = await _create(db_session, uid)
        row = await repo.get_by_id(db_session, mid)
        assert row is not None and row.id == mid

    async def test_get_by_id_missing_returns_none(self, db_session: AsyncSession) -> None:
        assert await repo.get_by_id(db_session, 999999) is None
