"""`drama_service` CRUD 测试:建 / 列 / 改 / 软删 + 跨用户 `NotFound`(D1/D14)。"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import NotFound
from drama_smith.db.repositories import user_repo
from drama_smith.services import drama_service as svc


async def _make_user(s: AsyncSession, username: str = "alice") -> int:
    return (await user_repo.create(s, username=username, password_hash="hash")).id


class TestDramaCRUD:
    async def test_create_first_sort_order_zero(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        d = await svc.create_drama(db_session, uid, name="d1")
        assert d.sort_order == 0
        assert d.name == "d1"

    async def test_list_orders_by_sort_order(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        await svc.create_drama(db_session, uid, name="d1")
        await svc.create_drama(db_session, uid, name="d2")
        dramas = await svc.list_dramas(db_session, uid)
        assert [d.name for d in dramas] == ["d1", "d2"]
        assert [d.sort_order for d in dramas] == [0, 1]

    async def test_rename(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        d = await svc.create_drama(db_session, uid, name="d")
        await svc.rename_drama(db_session, uid, d.id, name="renamed")
        assert (await svc.get_drama(db_session, uid, d.id)).name == "renamed"

    async def test_delete_soft_hides_from_list(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        d = await svc.create_drama(db_session, uid, name="d")
        await svc.delete_drama(db_session, uid, d.id)
        assert await svc.list_dramas(db_session, uid) == []
        # 软删后 get 也 NotFound(repo 排除 deleted_at)
        with pytest.raises(NotFound):
            await svc.get_drama(db_session, uid, d.id)

    async def test_cross_user_not_found(self, db_session: AsyncSession) -> None:
        a = await _make_user(db_session, "alice")
        b = await _make_user(db_session, "bob")
        d = await svc.create_drama(db_session, a, name="d")
        with pytest.raises(NotFound):
            await svc.get_drama(db_session, b, d.id)
        # 跨用户 rename / delete 同样 NotFound
        with pytest.raises(NotFound):
            await svc.rename_drama(db_session, b, d.id, name="x")
        with pytest.raises(NotFound):
            await svc.delete_drama(db_session, b, d.id)
