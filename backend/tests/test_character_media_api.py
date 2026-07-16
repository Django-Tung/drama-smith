"""M3 角色形象图全流水线 HTTP 集成测试。

覆盖形象图三端点(upload 同步 / generate 异步轮询 / get 读)+ 内容端点签名 URL 直读 +
门禁(无 active 图片配置 → 409 model_not_configured;角色未填 `appearance_desc` → 409
invalid_state;上传非图片 → 422 media_invalid;超大 → 413 media_too_large)+ 单选替换(D9,
旧图翻 selected=False 但保留)+ 跨用户 404 + 内容端点凭证校验(坏 token / 错 media_id / 不存在)。

执行器 + FileStore 双注入:`conftest.client` 不触发 lifespan,本模块覆写 client,手置
`app.state.executor` + `app.state.file_store`(真实 `LocalFileStore` 落 `tmp_path`,测全链路
save→sign→content 端点字节往返)。image LLM 经 monkeypatch `llm_factory.build` → `_StubImageModel`,
`generate` 返回 data URI(内嵌 Pillow 生成的微小 PNG),避开真实 HTTP、兼测 data-URI 下载路径。
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncEngine

from drama_smith.core.config import get_settings
from drama_smith.db.base import get_session_factory
from drama_smith.llm import factory as llm_factory
from drama_smith.main import create_app
from drama_smith.storage import LocalFileStore
from drama_smith.tasks import TaskExecutor
from tests.helpers import RegisterUser, unique_username

_PASSWORD = "Sup3rSecret!"
_TERMINAL = ("succeeded", "failed", "canceled", "interrupted")


def _make_png(color: tuple[int, int, int] = (200, 50, 50)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


_PNG_BYTES = _make_png()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _StubImageModel:
    """image LLM 替身:`generate` 返回内嵌微小 PNG 的 data URI(避开真实 HTTP,兼测 data-URI 路径)。

    `ImageModel` 为 `runtime_checkable Protocol`,本类 `generate`/`probe` 鸭子类型即过 `isinstance`。
    """

    async def generate(self, prompt: str, **params: Any) -> str:
        del prompt, params
        return "data:image/png;base64," + base64.b64encode(_PNG_BYTES).decode()

    async def probe(self) -> None:
        return None


@pytest_asyncio.fixture
async def client(
    db_engine: AsyncEngine, tmp_path: Path
) -> AsyncIterator[AsyncClient]:
    """覆写 conftest.client:注入执行器 + FileStore(portrait 端点需两者)。

    FileStore 用真实 `LocalFileStore` 落 `tmp_path`,复用 `jwt_secret` 签名;
    收尾 `executor.shutdown()`。
    """
    del db_engine  # 仅保证测试库就绪 / 截断夹具顺序
    app = create_app()
    app.state.executor = TaskExecutor(get_session_factory(), 4, 8)
    settings = get_settings()
    app.state.file_store = LocalFileStore(
        tmp_path,
        settings.jwt_secret.get_secret_value(),
        settings.media_signed_url_ttl_seconds,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    await app.state.executor.shutdown()


async def _register(
    client: AsyncClient, register_user: RegisterUser, username: str | None = None
) -> str:
    data = await register_user(username=username or unique_username(), password=_PASSWORD)
    return str(data["access_token"])


async def _create_image_config(client: AsyncClient, token: str) -> None:
    """建一条 active 图片配置(首次自动 active)→ 满足形象图生成门禁。"""
    resp = await client.post(
        "/api/me/models",
        json={
            "purpose": "image",
            "provider": "seedream",
            "model": "seedream-3.0",
            "api_key": "sk-fake-image-99988877766",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text


async def _seed_episode(client: AsyncClient, token: str) -> tuple[int, int]:
    did = (await client.post("/api/dramas", json={"name": "d"}, headers=_auth(token))).json()[
        "data"
    ]["id"]
    ep = (
        await client.post(
            f"/api/dramas/{did}/episodes",
            json={"title": "e", "aspect_ratio": "16:9"},
            headers=_auth(token),
        )
    ).json()["data"]["id"]
    return did, ep


async def _create_character(
    client: AsyncClient,
    token: str,
    ep: int,
    *,
    name: str = "小明",
    appearance_desc: str | None = "短发,穿白衬衫",
) -> int:
    return (
        await client.post(
            f"/api/episodes/{ep}/characters",
            json={"name": name, "appearance_desc": appearance_desc},
            headers=_auth(token),
        )
    ).json()["data"]["id"]


async def _poll_task(client: AsyncClient, token: str, task_id: int) -> dict[str, Any]:
    for _ in range(200):
        resp = await client.get(f"/api/tasks/{task_id}", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        task = resp.json()["data"]
        if task["status"] in _TERMINAL:
            return task
        await asyncio.sleep(0.02)
    raise AssertionError(f"task {task_id} did not terminate in time")


def _signed_url_media_id(view: dict[str, Any]) -> int:
    """从 GET portrait 返回的 signed_url 解析 media_id(路径段 /api/media/<id>/content)。"""
    return int(view["signed_url"].split("/")[3])


class TestPortraitUpload:
    async def test_upload_then_get_then_content(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        t = await _register(client, register_user)
        _, ep = await _seed_episode(client, t)
        cid = await _create_character(client, t, ep)

        # 上传 PNG → 201 + MediaPublic(含签名 URL)
        up = await client.post(
            f"/api/episodes/{ep}/characters/{cid}/portrait/upload",
            files={"file": ("p.png", _PNG_BYTES, "image/png")},
            headers=_auth(t),
        )
        assert up.status_code == 201, up.text
        view = up.json()["data"]
        assert view["source"] == "upload"
        assert view["content_type"] == "image/png"
        mid = view["media_id"]

        # GET 当前形象图 → 同一 media_id + 签名 URL
        got = (
            await client.get(
                f"/api/episodes/{ep}/characters/{cid}/portrait", headers=_auth(t)
            )
        ).json()["data"]
        assert got["media_id"] == mid
        assert _signed_url_media_id(got) == mid

        # 内容端点(免 Authorization,凭证在 query)→ 字节往返一致
        content = await client.get(view["signed_url"])
        assert content.status_code == 200
        assert content.content == _PNG_BYTES

        # 角色指针已更新
        char = (
            await client.get(
                f"/api/episodes/{ep}/characters/{cid}", headers=_auth(t)
            )
        ).json()["data"]
        assert char["image_media_id"] == mid

    async def test_upload_replaces_old_selected(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        t = await _register(client, register_user)
        _, ep = await _seed_episode(client, t)
        cid = await _create_character(client, t, ep)
        first = (
            await client.post(
                f"/api/episodes/{ep}/characters/{cid}/portrait/upload",
                files={"file": ("a.png", _make_png((10, 10, 10)), "image/png")},
                headers=_auth(t),
            )
        ).json()["data"]["media_id"]
        second = (
            await client.post(
                f"/api/episodes/{ep}/characters/{cid}/portrait/upload",
                files={"file": ("b.png", _make_png((20, 20, 20)), "image/png")},
                headers=_auth(t),
            )
        ).json()["data"]["media_id"]
        # 当前指向第二次上传;旧 media 行保留(D9)但不再 selected
        current = (
            await client.get(
                f"/api/episodes/{ep}/characters/{cid}/portrait", headers=_auth(t)
            )
        ).json()["data"]
        assert current["media_id"] == second
        assert first != second

    async def test_upload_non_image_is_422(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        t = await _register(client, register_user)
        _, ep = await _seed_episode(client, t)
        cid = await _create_character(client, t, ep)
        resp = await client.post(
            f"/api/episodes/{ep}/characters/{cid}/portrait/upload",
            files={"file": ("not.png", b"definitely not an image", "image/png")},
            headers=_auth(t),
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "media_invalid"

    async def test_upload_too_large_is_413(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 调低硬上限,使合法小 PNG 也超限 → 413(校验先于解码)
        monkeypatch.setattr(
            "drama_smith.api.characters.get_settings",
            lambda: SimpleNamespace(media_upload_max_bytes=8),
        )
        t = await _register(client, register_user)
        _, ep = await _seed_episode(client, t)
        cid = await _create_character(client, t, ep)
        resp = await client.post(
            f"/api/episodes/{ep}/characters/{cid}/portrait/upload",
            files={"file": ("p.png", _PNG_BYTES, "image/png")},
            headers=_auth(t),
        )
        assert resp.status_code == 413
        assert resp.json()["error"]["code"] == "media_too_large"

    async def test_get_no_portrait_is_204(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        t = await _register(client, register_user)
        _, ep = await _seed_episode(client, t)
        cid = await _create_character(client, t, ep)
        resp = await client.get(
            f"/api/episodes/{ep}/characters/{cid}/portrait", headers=_auth(t)
        )
        assert resp.status_code == 204
        assert resp.content == b""

    async def test_cross_user_is_404(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        t = await _register(client, register_user)
        _, ep = await _seed_episode(client, t)
        cid = await _create_character(client, t, ep)
        t2 = await _register(client, register_user)
        # 他人 GET / POST / 内容 均不泄露(嵌套资源 404)
        assert (
            await client.get(
                f"/api/episodes/{ep}/characters/{cid}/portrait", headers=_auth(t2)
            )
        ).status_code == 404
        assert (
            await client.post(
                f"/api/episodes/{ep}/characters/{cid}/portrait/upload",
                files={"file": ("p.png", _PNG_BYTES, "image/png")},
                headers=_auth(t2),
            )
        ).status_code == 404


class TestPortraitGenerate:
    async def test_generate_success_poll_and_read(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(llm_factory, "build", lambda snap, key: _StubImageModel())
        t = await _register(client, register_user)
        await _create_image_config(client, t)
        _, ep = await _seed_episode(client, t)
        cid = await _create_character(client, t, ep, appearance_desc="短发白衬衫少年")

        resp = await client.post(
            f"/api/episodes/{ep}/characters/{cid}/portrait/generate", headers=_auth(t)
        )
        assert resp.status_code == 202
        task = await _poll_task(client, t, resp.json()["data"]["id"])
        assert task["status"] == "succeeded"
        mid = task["output_refs"]["media_id"]

        # 当前形象图已切到生成图;内容端点字节 = 替身 PNG
        view = (
            await client.get(
                f"/api/episodes/{ep}/characters/{cid}/portrait", headers=_auth(t)
            )
        ).json()["data"]
        assert view["media_id"] == mid
        assert view["source"] == "generate"
        content = await client.get(view["signed_url"])
        assert content.status_code == 200
        assert content.content == _PNG_BYTES

    async def test_generate_no_config_is_409(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(llm_factory, "build", lambda snap, key: _StubImageModel())
        t = await _register(client, register_user)
        _, ep = await _seed_episode(client, t)
        cid = await _create_character(client, t, ep)
        resp = await client.post(
            f"/api/episodes/{ep}/characters/{cid}/portrait/generate", headers=_auth(t)
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "model_not_configured"

    async def test_generate_no_appearance_is_409(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(llm_factory, "build", lambda snap, key: _StubImageModel())
        t = await _register(client, register_user)
        await _create_image_config(client, t)
        _, ep = await _seed_episode(client, t)
        cid = await _create_character(client, t, ep, appearance_desc=None)
        resp = await client.post(
            f"/api/episodes/{ep}/characters/{cid}/portrait/generate", headers=_auth(t)
        )
        assert resp.status_code == 409
        body = resp.json()["error"]
        assert body["code"] == "invalid_state"
        assert body["details"]["reason"] == "appearance_required"

    async def test_generate_cross_user_is_404(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(llm_factory, "build", lambda snap, key: _StubImageModel())
        t = await _register(client, register_user)
        await _create_image_config(client, t)
        _, ep = await _seed_episode(client, t)
        cid = await _create_character(client, t, ep)
        t2 = await _register(client, register_user)
        resp = await client.post(
            f"/api/episodes/{ep}/characters/{cid}/portrait/generate", headers=_auth(t2)
        )
        assert resp.status_code == 404


class TestMediaContent:
    """内容端点凭证校验:坏 token / 错 media_id / 不存在。"""

    async def test_bad_token_is_401(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        # 不经鉴权(端点免 Authorization);坏 token → 401
        resp = await client.get("/api/media/1/content?token=garbage&exp=1")
        assert resp.status_code == 401

    async def test_mismatched_media_id_is_401(self, tmp_path: Path) -> None:
        # 用真实 secret 签 media 42 的 token,却请求 media 43 → sub 不符 → 401
        signer = LocalFileStore(tmp_path, get_settings().jwt_secret.get_secret_value(), 300)
        token, exp = signer.sign(42)
        # 独立 client(无 executor 需求,内容端点只用 file_store)
        app = create_app()
        app.state.file_store = LocalFileStore(
            tmp_path,
            get_settings().jwt_secret.get_secret_value(),
            get_settings().media_signed_url_ttl_seconds,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            resp = await ac.get(f"/api/media/43/content?token={token}&exp={exp}")
        assert resp.status_code == 401

    async def test_missing_media_is_404(self, tmp_path: Path) -> None:
        # 有效 token(签名真实、sub 匹配)但 media 不存在 → 404
        signer = LocalFileStore(tmp_path, get_settings().jwt_secret.get_secret_value(), 300)
        token, exp = signer.sign(999999)
        app = create_app()
        app.state.file_store = LocalFileStore(
            tmp_path,
            get_settings().jwt_secret.get_secret_value(),
            get_settings().media_signed_url_ttl_seconds,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            resp = await ac.get(f"/api/media/999999/content?token={token}&exp={exp}")
        assert resp.status_code == 404
