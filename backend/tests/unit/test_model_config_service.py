"""`model_config_service` 单元测试:create/update/delete/activate/test 各用例,
覆盖 D3/D4/D7/D8 与 FR-C5/C6。Fake LLM 替身(`tests/llm/fakes`)驱动自检三态。
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.llm.fakes import FakeTextModel

from drama_smith.core import crypto
from drama_smith.core.config import get_mek
from drama_smith.core.errors import (
    Conflict,
    ModelNotConfigured,
    NotFound,
    ProviderAuthFailed,
    RateLimited,
)
from drama_smith.db.repositories import user_repo
from drama_smith.llm.base import ProbeNotSupported
from drama_smith.services import model_config_service as svc

_MEK = get_mek()
_KEY = "sk-testkey-1234567890ABCDEF"


async def _make_user(session: AsyncSession, username: str = "alice") -> int:
    return (await user_repo.create(session, username=username, password_hash="hash")).id


async def _make_config(
    session: AsyncSession,
    uid: int,
    *,
    purpose: str = "text",
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    api_key: str = _KEY,
    **kwargs: Any,
) -> Any:
    return await svc.create_config(
        session,
        uid,
        purpose=purpose,
        provider=provider,
        model=model,
        api_key=api_key,
        mek=_MEK,
        **kwargs,
    )


def _decrypt(cfg: Any) -> str:
    return crypto.decrypt(crypto.Envelope(cfg.api_key_ciphertext, cfg.dek_ciphertext), _MEK)


def _fake_factory(probe_raises: type[Exception] | None = None) -> Any:
    """构造忽略 (snapshot,key)、回放固定 probe 行为的接缝替身工厂。"""
    return lambda _snapshot, _key: FakeTextModel(probe_raises=probe_raises)


class TestCreate:
    async def test_first_is_auto_active(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        cfg = await _make_config(db_session, uid)
        assert cfg.is_active is True

    async def test_second_same_purpose_is_inactive(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        first = await _make_config(db_session, uid, model="m1")
        second = await _make_config(db_session, uid, provider="deepseek", model="m2")
        assert first.is_active is True
        assert second.is_active is False

    async def test_different_purpose_each_auto_active(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        text = await _make_config(db_session, uid, purpose="text")
        image = await _make_config(db_session, uid, purpose="image", provider="seedream")
        assert text.is_active is True
        assert image.is_active is True

    async def test_invalid_provider_raises_value_error(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        # seedream 是 image-only,放进 text → ValueError(API 层应先 422,此为兜底)
        with pytest.raises(ValueError, match="not supported for purpose"):
            await _make_config(db_session, uid, provider="seedream")

    async def test_masked_stored_not_plaintext(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        cfg = await _make_config(db_session, uid)
        assert cfg.api_key_masked == crypto.mask_key(_KEY)
        assert _KEY not in cfg.api_key_masked
        assert _decrypt(cfg) == _KEY  # 密文可还原明文


class TestUpdate:
    async def test_without_key_preserves_crypto(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        cfg = await _make_config(db_session, uid)
        updated = await svc.update_config(db_session, uid, cfg.id, mek=_MEK, model="new-model")
        assert updated.model == "new-model"
        assert updated.api_key_masked == cfg.api_key_masked  # 脱敏串未变(D8)
        assert _decrypt(updated) == _KEY  # 密文仍解出原 key

    async def test_with_key_reseals(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        cfg = await _make_config(db_session, uid)
        new_key = "sk-brandnew-99988877766"
        updated = await svc.update_config(db_session, uid, cfg.id, mek=_MEK, api_key=new_key)
        assert updated.api_key_masked == crypto.mask_key(new_key)
        assert _decrypt(updated) == new_key

    async def test_clear_base_url(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        cfg = await _make_config(db_session, uid, base_url="https://x.test/v1")
        assert cfg.base_url == "https://x.test/v1"
        updated = await svc.update_config(db_session, uid, cfg.id, mek=_MEK, base_url=None)
        assert updated.base_url is None


class TestActivate:
    async def test_activate_flips_uniquely(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        a = await _make_config(db_session, uid, model="a")
        b = await _make_config(db_session, uid, provider="deepseek", model="b")
        assert a.is_active is True and b.is_active is False
        await svc.activate_config(db_session, uid, b.id)
        await db_session.refresh(a)
        await db_session.refresh(b)
        assert a.is_active is False and b.is_active is True


class TestDelete:
    async def _active_sibling(self, session: AsyncSession, uid: int) -> tuple[int, int]:
        a = await _make_config(session, uid, model="a")
        b = await _make_config(session, uid, provider="deepseek", model="b")
        return a.id, b.id

    async def test_active_with_siblings_requires_successor(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        a_id, _ = await self._active_sibling(db_session, uid)
        with pytest.raises(Conflict) as exc_info:
            await svc.delete_config(db_session, uid, a_id)
        assert exc_info.value.details.get("reason") == "invalid_state"

    async def test_active_with_successor_promotes(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        a_id, b_id = await self._active_sibling(db_session, uid)
        await svc.delete_config(db_session, uid, a_id, new_active_id=b_id)
        b = await svc.get_config(db_session, uid, b_id)
        assert b.is_active is True
        with pytest.raises(NotFound):
            await svc.get_config(db_session, uid, a_id)

    async def test_active_no_siblings_ok(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        cfg = await _make_config(db_session, uid)
        await svc.delete_config(db_session, uid, cfg.id)
        with pytest.raises(NotFound):
            await svc.get_config(db_session, uid, cfg.id)

    async def test_inactive_delete_ok(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        await _make_config(db_session, uid, model="a")
        b = await _make_config(db_session, uid, provider="deepseek", model="b")
        assert b.is_active is False
        await svc.delete_config(db_session, uid, b.id)
        with pytest.raises(NotFound):
            await svc.get_config(db_session, uid, b.id)

    async def test_bad_successor_not_found(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        a_id, _ = await self._active_sibling(db_session, uid)
        img = await _make_config(db_session, uid, purpose="image", provider="seedream")
        # 继任指向其它 purpose 的配置 → NotFound
        with pytest.raises(NotFound):
            await svc.delete_config(db_session, uid, a_id, new_active_id=img.id)


class TestSelfTest:
    async def test_success_updates_last_tested(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        cfg = await _make_config(db_session, uid)
        out = await svc.test_config(
            db_session, uid, cfg.id, mek=_MEK, model_factory=_fake_factory()
        )
        assert out.last_tested_at is not None
        assert out.status == "active"

    async def test_auth_fail_marks_invalid_and_raises(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        cfg = await _make_config(db_session, uid)
        with pytest.raises(ProviderAuthFailed):
            await svc.test_config(
                db_session,
                uid,
                cfg.id,
                mek=_MEK,
                model_factory=_fake_factory(ProviderAuthFailed),
            )
        assert (await svc.get_config(db_session, uid, cfg.id)).status == "invalid"

    async def test_rate_limited_raises_not_invalid(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        cfg = await _make_config(db_session, uid)
        with pytest.raises(RateLimited):
            await svc.test_config(
                db_session, uid, cfg.id, mek=_MEK, model_factory=_fake_factory(RateLimited)
            )
        # 瞬态限流不置 invalid(D7:仅鉴权失败置 invalid)
        assert (await svc.get_config(db_session, uid, cfg.id)).status == "active"

    async def test_probe_not_supported_degrades(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        cfg = await _make_config(db_session, uid)
        out = await svc.test_config(
            db_session, uid, cfg.id, mek=_MEK, model_factory=_fake_factory(ProbeNotSupported)
        )
        assert out.last_tested_at is not None
        assert out.status == "active"

    async def test_cross_user_not_found(self, db_session: AsyncSession) -> None:
        uid_a = await _make_user(db_session, "alice")
        uid_b = await _make_user(db_session, "bob")
        cfg = await _make_config(db_session, uid_a)
        with pytest.raises(NotFound):
            await svc.test_config(
                db_session, uid_b, cfg.id, mek=_MEK, model_factory=_fake_factory()
            )


class TestRequireActiveText:
    async def test_raises_when_none(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        with pytest.raises(ModelNotConfigured):
            await svc.require_active_text(db_session, uid)

    async def test_ok_when_configured(self, db_session: AsyncSession) -> None:
        uid = await _make_user(db_session)
        await _make_config(db_session, uid)
        await svc.require_active_text(db_session, uid)  # 不抛即通过
