"""`episode_service` CRUD 测试:建 / 列 / 改 / 软删 + 画幅必填 + style_preset 清空(D1/D14)。"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import NotFound
from drama_smith.db.repositories import user_repo
from drama_smith.services import drama_service
from drama_smith.services import episode_service as svc


async def _make_drama(s: AsyncSession, uid: int) -> int:
    return (await drama_service.create_drama(s, uid, name="d")).id


async def _make_user(s: AsyncSession, username: str = "alice") -> int:
    return (await user_repo.create(s, username=username, password_hash="hash")).id


class TestEpisodeCRUD:
    async def test_create_and_list_by_drama(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        did = await _make_drama(db_session, uid)
        await svc.create_episode(db_session, uid, did, title="e1", aspect_ratio="16:9")
        await svc.create_episode(db_session, uid, did, title="e2", aspect_ratio="9:16")
        eps = await svc.list_episodes(db_session, uid, did)
        assert [e.title for e in eps] == ["e1", "e2"]

    async def test_update_fields(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        did = await _make_drama(db_session, uid)
        ep = await svc.create_episode(
            db_session, uid, did, title="e", aspect_ratio="16:9", style_preset="cinematic"
        )
        assert ep.style_preset == "cinematic"
        updated = await svc.update_episode(db_session, uid, ep.id, title="e2", aspect_ratio="9:16")
        assert updated.title == "e2"
        assert updated.aspect_ratio == "9:16"
        assert updated.style_preset == "cinematic"  # 未传 → 不动

    async def test_update_style_preset_none_clears(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        did = await _make_drama(db_session, uid)
        ep = await svc.create_episode(
            db_session, uid, did, title="e", aspect_ratio="16:9", style_preset="cinematic"
        )
        updated = await svc.update_episode(db_session, uid, ep.id, style_preset=None)
        assert updated.style_preset is None  # 显式 None 清空

    async def test_delete_soft_hides(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        did = await _make_drama(db_session, uid)
        ep = await svc.create_episode(db_session, uid, did, title="e", aspect_ratio="16:9")
        await svc.delete_episode(db_session, uid, ep.id)
        assert await svc.list_episodes(db_session, uid, did) == []
        with pytest.raises(NotFound):
            await svc.get_episode(db_session, uid, ep.id)

    async def test_cross_drama_user_not_found(self, db_session: AsyncSession) -> None:
        a = await _make_user(db_session, "alice")
        b = await _make_user(db_session, "bob")
        did_a = await _make_drama(db_session, a)
        ep = await svc.create_episode(db_session, a, did_a, title="e", aspect_ratio="16:9")
        # 另一用户的剧集 → NotFound
        with pytest.raises(NotFound):
            await svc.get_episode(db_session, b, ep.id)
