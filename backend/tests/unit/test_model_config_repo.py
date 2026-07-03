"""`model_config_repo` 单元测试:active 唯一性(D3)、跨用户隔离(D6)、完成度信号(D9)。

直连测试库会话(经 `tests/conftest.py` 的 `db_session` 夹具),不走 HTTP。
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.config import get_mek
from drama_smith.core.crypto import encrypt, mask_key
from drama_smith.core.errors import Conflict, NotFound
from drama_smith.db.repositories import model_config_repo as repo
from drama_smith.db.repositories import user_repo


def _envelope(plaintext: str = "sk-testkey-1234567890ABC") -> tuple[bytes, bytes, str]:
    """产出真实信封三件套(repo 不解密,但用真实 blob 更贴近实际)。"""
    env = encrypt(plaintext, get_mek())
    return env.key_blob, env.dek_blob, mask_key(plaintext)


async def _make_user(session: AsyncSession, username: str = "alice") -> int:
    user = await user_repo.create(session, username=username, password_hash="hash")
    return user.id


class TestCreateAndActiveInvariant:
    async def test_first_active_counted(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        kb, db, masked = _envelope()
        await repo.create(
            db_session,
            uid,
            purpose="text",
            provider="openai",
            model="gpt-4o-mini",
            api_key_ciphertext=kb,
            dek_ciphertext=db,
            api_key_masked=masked,
            is_active=True,
        )
        assert await repo.count_active(db_session, uid, "text") == 1
        assert await repo.has_active_text(db_session, uid) is True

    async def test_second_active_same_purpose_rejected(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        kb, db, masked = _envelope()
        await repo.create(db_session, uid, purpose="text", provider="openai",
                          model="m1", api_key_ciphertext=kb, dek_ciphertext=db,
                          api_key_masked=masked, is_active=True)
        kb2, db2, masked2 = _envelope("sk-other-1234567890XYZ")
        with pytest.raises(Conflict):
            await repo.create(db_session, uid, purpose="text", provider="deepseek",
                              model="m2", api_key_ciphertext=kb2, dek_ciphertext=db2,
                              api_key_masked=masked2, is_active=True)

    async def test_inactive_rows_coexist(self, db_session: AsyncSession) -> None:
        # 非 active 行 active_key=NULL,UNIQUE 不冲突 → 可共存(D3)。
        uid = await _make_user(db_session)
        for i in range(3):
            kb, db, masked = _envelope(f"sk-key-{i}-1234567890AB")
            await repo.create(db_session, uid, purpose="image", provider="openai",
                              model=f"img{i}", api_key_ciphertext=kb, dek_ciphertext=db,
                              api_key_masked=masked, is_active=False)
        assert await repo.count_active(db_session, uid, "image") == 0


class TestActivate:
    async def test_activate_flips_uniquely(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        kb, db, masked = _envelope()
        a = await repo.create(db_session, uid, purpose="text", provider="openai",
                              model="a", api_key_ciphertext=kb, dek_ciphertext=db,
                              api_key_masked=masked, is_active=True)
        kb2, db2, masked2 = _envelope("sk-second-1234567890XY")
        b = await repo.create(db_session, uid, purpose="text", provider="deepseek",
                              model="b", api_key_ciphertext=kb2, dek_ciphertext=db2,
                              api_key_masked=masked2, is_active=False)
        await repo.activate(db_session, uid, b.id)
        await db_session.refresh(a)
        await db_session.refresh(b)
        assert a.is_active is False
        assert b.is_active is True
        assert await repo.count_active(db_session, uid, "text") == 1

    async def test_activate_one_purpose_isolated(self, db_session: AsyncSession) -> None:
        # 激活 text 不应触碰 image 的 active。
        uid = await _make_user(db_session)
        kb, db, masked = _envelope()
        img = await repo.create(db_session, uid, purpose="image", provider="openai",
                                model="img", api_key_ciphertext=kb, dek_ciphertext=db,
                                api_key_masked=masked, is_active=True)
        kb2, db2, masked2 = _envelope("sk-t-1234567890AB")
        txt = await repo.create(db_session, uid, purpose="text", provider="openai",
                                model="txt", api_key_ciphertext=kb2, dek_ciphertext=db2,
                                api_key_masked=masked2, is_active=True)
        # 激活另一个 text(先加一条 inactive text 再激活)
        kb3, db3, masked3 = _envelope("sk-t2-1234567890AB")
        txt2 = await repo.create(db_session, uid, purpose="text", provider="deepseek",
                                 model="txt2", api_key_ciphertext=kb3, dek_ciphertext=db3,
                                 api_key_masked=masked3, is_active=False)
        await repo.activate(db_session, uid, txt2.id)
        await db_session.refresh(img)
        await db_session.refresh(txt)
        assert img.is_active is True  # image 的 active 未受影响
        assert txt.is_active is False


class TestIsolationAndSignals:
    async def test_get_cross_user_not_found(self, db_session: AsyncSession) -> None:
        uid_a = await _make_user(db_session, "alice")
        uid_b = await _make_user(db_session, "bob")
        kb, db, masked = _envelope()
        cfg = await repo.create(db_session, uid_a, purpose="text", provider="openai",
                                model="m", api_key_ciphertext=kb, dek_ciphertext=db,
                                api_key_masked=masked, is_active=True)
        # bob 访问 alice 的配置 → NotFound(不泄露存在性)
        with pytest.raises(NotFound):
            await repo.get(db_session, uid_b, cfg.id)

    async def test_has_active_text_tracks_lifecycle(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        assert await repo.has_active_text(db_session, uid) is False
        kb, db, masked = _envelope()
        cfg = await repo.create(db_session, uid, purpose="text", provider="openai",
                                model="m", api_key_ciphertext=kb, dek_ciphertext=db,
                                api_key_masked=masked, is_active=True)
        assert await repo.has_active_text(db_session, uid) is True
        await repo.delete(db_session, cfg)
        assert await repo.has_active_text(db_session, uid) is False

    async def test_image_only_does_not_set_text_flag(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        kb, db, masked = _envelope()
        await repo.create(db_session, uid, purpose="image", provider="openai",
                          model="img", api_key_ciphertext=kb, dek_ciphertext=db,
                          api_key_masked=masked, is_active=True)
        assert await repo.has_active_text(db_session, uid) is False

    async def test_set_status_invalid(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        kb, db, masked = _envelope()
        cfg = await repo.create(db_session, uid, purpose="text", provider="openai",
                                model="m", api_key_ciphertext=kb, dek_ciphertext=db,
                                api_key_masked=masked, is_active=True)
        await repo.set_status(db_session, uid, cfg.id, "invalid")
        await db_session.refresh(cfg)
        assert cfg.status == "invalid"
