"""任务 8.7:模型配置 API 集成测试(CRUD / activate / test / `/api/me` 标记)。

覆盖 BYOK 端点正常与异常路径、跨用户 404、`/api/me` 完成度标记随配置翻转。
自检端点经 monkeypatch 把 `llm_factory.build` 换成 `FakeTextModel`,避免真实网络
(`design.md` D6:真实供应商探测仅手动验收)。
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from drama_smith.core.errors import ProviderAuthFailed
from drama_smith.llm import factory as llm_factory
from tests.helpers import RegisterUser, unique_username
from tests.llm.fakes import FakeTextModel

_PASSWORD = "Sup3rSecret!"
_KEY = "sk-integration-1234567890ABC"


def _auth(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _body(
    *,
    purpose: str = "text",
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    api_key: str = _KEY,
    **kwargs: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "purpose": purpose,
        "provider": provider,
        "model": model,
        "api_key": api_key,
    }
    payload.update(kwargs)
    return payload


async def _register(
    client: AsyncClient, register_user: RegisterUser, username: str | None = None
) -> str:
    data = await register_user(username=username or unique_username(), password=_PASSWORD)
    return str(data["access_token"])


class TestCreateAndRead:
    async def test_create_then_list_get_and_me_flag_flips(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        token = await _register(client, register_user)
        h = _auth(token)
        # 配 text 之前:标记 false
        me0 = (await client.get("/api/me", headers=h)).json()["data"]
        assert me0["text_model_configured"] is False

        resp = await client.post("/api/me/models", json=_body(), headers=h)
        assert resp.status_code == 201, resp.text
        cfg = resp.json()["data"]
        assert cfg["is_active"] is True
        assert cfg["api_key_masked"]
        assert "api_key" not in cfg  # 明文永不回显
        cid = cfg["id"]

        # 配 text 之后:标记 true
        me1 = (await client.get("/api/me", headers=h)).json()["data"]
        assert me1["text_model_configured"] is True

        lst = (await client.get("/api/me/models", headers=h)).json()["data"]
        assert len(lst) == 1 and lst[0]["id"] == cid
        one = (await client.get(f"/api/me/models/{cid}", headers=h)).json()["data"]
        assert one["id"] == cid

    async def test_create_invalid_provider_is_422(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        token = await _register(client, register_user)
        # seedream 是 image-only,放进 text → 白名单 422
        resp = await client.post(
            "/api/me/models", json=_body(provider="seedream"), headers=_auth(token)
        )
        assert resp.status_code == 422

    async def test_image_does_not_set_text_flag(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        token = await _register(client, register_user)
        await client.post(
            "/api/me/models",
            json=_body(purpose="image", provider="seedream"),
            headers=_auth(token),
        )
        me = (await client.get("/api/me", headers=_auth(token))).json()["data"]
        assert me["text_model_configured"] is False


class TestUpdate:
    async def test_update_without_key_preserves_masked(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        token = await _register(client, register_user)
        h = _auth(token)
        cid = (await client.post("/api/me/models", json=_body(), headers=h)).json()["data"]["id"]
        masked_before = (await client.get(f"/api/me/models/{cid}", headers=h)).json()["data"][
            "api_key_masked"
        ]
        resp = await client.put(f"/api/me/models/{cid}", json={"model": "new-model"}, headers=h)
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["api_key_masked"] == masked_before  # D8:未给 key 不动加密列

    async def test_update_with_key_reseals(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        token = await _register(client, register_user)
        h = _auth(token)
        cid = (await client.post("/api/me/models", json=_body(), headers=h)).json()["data"]["id"]
        resp = await client.put(
            f"/api/me/models/{cid}", json={"api_key": "sk-newkey-99988877766"}, headers=h
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["api_key_masked"].endswith("7766")  # 脱敏串已变(末 4)


class TestActivate:
    async def test_activate_flips(self, client: AsyncClient, register_user: RegisterUser) -> None:
        token = await _register(client, register_user)
        h = _auth(token)
        a = (await client.post("/api/me/models", json=_body(model="a"), headers=h)).json()["data"]
        b = (
            await client.post(
                "/api/me/models", json=_body(provider="deepseek", model="b"), headers=h
            )
        ).json()["data"]
        assert a["is_active"] is True and b["is_active"] is False
        resp = await client.post(f"/api/me/models/{b['id']}/activate", headers=h)
        assert resp.status_code == 200
        assert resp.json()["data"]["is_active"] is True
        a2 = (await client.get(f"/api/me/models/{a['id']}", headers=h)).json()["data"]
        assert a2["is_active"] is False


class TestDelete:
    async def test_delete_active_with_sibling_requires_successor(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        token = await _register(client, register_user)
        h = _auth(token)
        a = (await client.post("/api/me/models", json=_body(model="a"), headers=h)).json()["data"]
        await client.post("/api/me/models", json=_body(provider="deepseek", model="b"), headers=h)
        resp = await client.delete(f"/api/me/models/{a['id']}", headers=h)
        assert resp.status_code == 409
        assert resp.json()["error"]["details"]["reason"] == "invalid_state"

    async def test_delete_active_with_successor(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        token = await _register(client, register_user)
        h = _auth(token)
        a = (await client.post("/api/me/models", json=_body(model="a"), headers=h)).json()["data"]
        b = (
            await client.post(
                "/api/me/models", json=_body(provider="deepseek", model="b"), headers=h
            )
        ).json()["data"]
        resp = await client.delete(f"/api/me/models/{a['id']}?new_active_id={b['id']}", headers=h)
        assert resp.status_code == 204
        assert (await client.get(f"/api/me/models/{a['id']}", headers=h)).status_code == 404
        b2 = (await client.get(f"/api/me/models/{b['id']}", headers=h)).json()["data"]
        assert b2["is_active"] is True

    async def test_delete_sole_active_clears_text_flag(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        token = await _register(client, register_user)
        h = _auth(token)
        a = (await client.post("/api/me/models", json=_body(), headers=h)).json()["data"]
        resp = await client.delete(f"/api/me/models/{a['id']}", headers=h)
        assert resp.status_code == 204
        me = (await client.get("/api/me", headers=h)).json()["data"]
        assert me["text_model_configured"] is False


class TestSelfTest:
    async def test_self_test_success(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        token = await _register(client, register_user)
        h = _auth(token)
        cid = (await client.post("/api/me/models", json=_body(), headers=h)).json()["data"]["id"]
        monkeypatch.setattr(llm_factory, "build", lambda _s, _k: FakeTextModel())
        resp = await client.post(f"/api/me/models/{cid}/test", headers=h)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["last_tested_at"] is not None
        assert data["status"] == "active"

    async def test_self_test_auth_fail_502_and_marks_invalid(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        token = await _register(client, register_user)
        h = _auth(token)
        cid = (await client.post("/api/me/models", json=_body(), headers=h)).json()["data"]["id"]
        monkeypatch.setattr(
            llm_factory, "build", lambda _s, _k: FakeTextModel(probe_raises=ProviderAuthFailed)
        )
        resp = await client.post(f"/api/me/models/{cid}/test", headers=h)
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "provider_auth_failed"
        cfg = (await client.get(f"/api/me/models/{cid}", headers=h)).json()["data"]
        assert cfg["status"] == "invalid"


class TestIsolation:
    async def test_cross_user_get_is_404(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        token_a = await _register(client, register_user)
        token_b = await _register(client, register_user)
        cid = (await client.post("/api/me/models", json=_body(), headers=_auth(token_a))).json()[
            "data"
        ]["id"]
        resp = await client.get(f"/api/me/models/{cid}", headers=_auth(token_b))
        assert resp.status_code == 404  # 越权不泄露存在性

    async def test_unauthenticated_is_401(self, client: AsyncClient) -> None:
        resp = await client.get("/api/me/models")
        assert resp.status_code == 401
