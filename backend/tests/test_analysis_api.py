"""任务 10.8:M2 结构化分析全流水线 HTTP 集成测试。

覆盖 `/api` 下剧目 / 剧集 / 剧本 / 角色 / 分析 / 分镜 / 任务全链路:每端点 happy + 关键错误
(409 门禁/串行、422 无剧本、404 跨用户)+ Fake-LLM analyze/optimize 异步轮询 + cancel。

执行器注入:`conftest.client` 不触发 lifespan(故无 `app.state.executor`);本模块覆写 `client`,
手置 `app.state.executor = TaskExecutor(...)`(与全 suite 共享 session 级事件循环,执行器与引擎
同 loop)。LLM 经 monkeypatch `llm_factory.build` → 按 system 提示路由的 `_RoutingTextModel`
(analyze 五节点 + optimize copy-edit),`TextModel` 为 `runtime_checkable Protocol`,鸭子类型即过
`isinstance`。cancel / 串行门禁用 `asyncio.Event` 闸门让在途任务可观测地「卡住」。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from drama_smith.db.base import get_session_factory
from drama_smith.llm import factory as llm_factory
from drama_smith.main import create_app
from drama_smith.tasks import TaskExecutor
from tests.helpers import RegisterUser, unique_username

_PASSWORD = "Sup3rSecret!"
_TERMINAL = ("succeeded", "failed", "canceled", "interrupted")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _RoutingTextModel:
    """按 system 提示关键词路由的替身:analyze 五节点 + optimize copy-edit。

    `gate` 给定且未置位时,每次 `chat` 先 `await gate.wait()`——供 cancel / 串行门禁测试
    让在途任务可观测地卡住(成功路径测试给 `gate=None`,瞬时完成)。`TextModel` 为
    `runtime_checkable Protocol`,本类的 `chat`/`probe` 鸭子类型即过 `isinstance`。
    """

    def __init__(self, gate: asyncio.Event | None = None) -> None:
        self.gate = gate

    async def chat(self, messages: Sequence[Mapping[str, str]], **params: Any) -> str:
        del params
        if self.gate is not None:
            await self.gate.wait()
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        # 路由顺序:optimize(润色)先截;analyze 内 split_shots 的 system 含「角色」(已知清单),
        # 须先被「分镜」截走,「角色」放最后只匹配 extract_characters。
        if "润色" in system or "copy-edit" in system:
            return '{"content":"第一幕:小明走进咖啡馆,遇见阿珍。(优化版)"}'
        if "分镜" in system:
            return (
                '{"shots":[{"description":"小明进门","appearing":["小明"],'
                '"target_duration":5,"scene":"咖啡馆"}]}'
            )
        if "情节线" in system:
            return '{"plotlines":[{"name":"主线","type":"主线"}]}'
        if "冲突" in system:
            return '{"conflicts":[{"type":"人vs人","parties":"小明 vs 阿珍"}]}'
        if "节奏" in system:
            return '{"pacing":{"structure":"三幕","climax":"相遇"}}'
        if "角色" in system:
            return '{"characters":[{"name":"小明","role_type":"主角"}]}'
        return "{}"

    async def probe(self) -> None:
        return None


@pytest_asyncio.fixture
async def client(db_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    """覆写 conftest.client:注入执行器(analyze/optimize/cancel 需 `app.state.executor`)。

    与全 suite 共享 session 级事件循环;收尾 `executor.shutdown()` 收口在跑协程。
    """
    del db_engine  # 仅用于保证测试库已就绪 / 截断夹具顺序
    app = create_app()
    app.state.executor = TaskExecutor(get_session_factory(), 4, 8)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    await app.state.executor.shutdown()


async def _register(
    client: AsyncClient, register_user: RegisterUser, username: str | None = None
) -> str:
    data = await register_user(username=username or unique_username(), password=_PASSWORD)
    return str(data["access_token"])


async def _create_text_config(client: AsyncClient, token: str) -> None:
    """建一条 active 文本配置(首次自动 active;status 默认 active)→ 满足分析门禁。"""
    resp = await client.post(
        "/api/me/models",
        json={
            "purpose": "text",
            "provider": "deepseek",
            "model": "deepseek-ai/DeepSeek-V3.2",
            "api_key": "sk-fake-integration-99988877766",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text


async def _seed_episode(
    client: AsyncClient, token: str, *, script: str = "第一幕:小明走进咖啡馆。"
) -> tuple[int, int]:
    """建剧 + 剧集 + 写剧本;返回 (drama_id, episode_id)。"""
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
    resp = await client.put(
        f"/api/episodes/{ep}/script",
        json={"content": script, "format": "markdown"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    return did, ep


async def _poll_task(client: AsyncClient, token: str, task_id: int) -> dict[str, Any]:
    """轮询任务至终态(成功路径瞬时完成;cancel/串行测试先置闸门后释放)。"""
    for _ in range(200):
        resp = await client.get(f"/api/tasks/{task_id}", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        task = resp.json()["data"]
        if task["status"] in _TERMINAL:
            return task
        await asyncio.sleep(0.02)
    raise AssertionError(f"task {task_id} did not terminate in time")


async def _run_analyze(client: AsyncClient, token: str, episode_id: int) -> dict[str, Any]:
    """发起拆解并轮询至终态;返回终态 task。"""
    resp = await client.post(f"/api/episodes/{episode_id}/analyze", headers=_auth(token))
    assert resp.status_code == 202, resp.text
    task_id = resp.json()["data"]["id"]
    return await _poll_task(client, token, task_id)


class TestDramasAndEpisodes:
    async def test_crud_and_cross_user_404(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
    ) -> None:
        t = await _register(client, register_user)
        # 建剧 + 列表
        did = (await client.post("/api/dramas", json={"name": "剧A"}, headers=_auth(t))).json()[
            "data"
        ]["id"]
        lst = (await client.get("/api/dramas", headers=_auth(t))).json()["data"]
        assert len(lst) == 1 and lst[0]["id"] == did
        # 重命名 + 取详情
        renamed = (
            await client.put(f"/api/dramas/{did}", json={"name": "剧A2"}, headers=_auth(t))
        ).json()["data"]
        assert renamed["name"] == "剧A2"
        assert (await client.get(f"/api/dramas/{did}", headers=_auth(t))).status_code == 200
        # 建剧集 + 子集合列表
        ep = (
            await client.post(
                f"/api/dramas/{did}/episodes",
                json={"title": "e", "aspect_ratio": "9:16"},
                headers=_auth(t),
            )
        ).json()["data"]["id"]
        eps = (await client.get(f"/api/dramas/{did}/episodes", headers=_auth(t))).json()["data"]
        assert len(eps) == 1 and eps[0]["id"] == ep
        # 软删 + 列表归空
        assert (await client.delete(f"/api/dramas/{did}", headers=_auth(t))).status_code == 204
        assert (await client.get("/api/dramas", headers=_auth(t))).json()["data"] == []

        # 跨用户:另一用户看不到上者的剧 / 剧集(404,不泄露存在)
        t2 = await _register(client, register_user)
        assert (await client.get(f"/api/dramas/{did}", headers=_auth(t2))).status_code == 404
        assert (
            await client.get(f"/api/dramas/{did}/episodes", headers=_auth(t2))
        ).status_code == 404
        assert (await client.delete(f"/api/dramas/{did}", headers=_auth(t2))).status_code == 404


class TestScriptVersions:
    async def test_upsert_versions_select_reject(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
    ) -> None:
        t = await _register(client, register_user)
        _, ep = await _seed_episode(client, t)
        # 两次写入 → 两个 input 版本,current 指向后者
        await client.put(
            f"/api/episodes/{ep}/script",
            json={"content": "第二稿", "format": "markdown"},
            headers=_auth(t),
        )
        versions = (
            await client.get(f"/api/episodes/{ep}/script/versions", headers=_auth(t))
        ).json()["data"]
        assert len(versions) == 2
        assert all(v["source"] == "input" for v in versions)
        # select 回退到 v1(current 指针移动)
        v1 = versions[-1]["id"]  # 旧版在后(新→旧)
        sel = (
            await client.post(f"/api/episodes/{ep}/script/versions/{v1}/select", headers=_auth(t))
        ).json()["data"]
        assert sel["id"] == v1
        # reject:no-op,指针不动、版本仍在(列仍是 2 条)
        assert (
            await client.post(f"/api/episodes/{ep}/script/versions/{v1}/reject", headers=_auth(t))
        ).status_code == 204
        assert (
            len(
                (await client.get(f"/api/episodes/{ep}/script/versions", headers=_auth(t))).json()[
                    "data"
                ]
            )
            == 2
        )

        # 跨用户 404
        t2 = await _register(client, register_user)
        assert (
            await client.get(f"/api/episodes/{ep}/script/versions", headers=_auth(t2))
        ).status_code == 404


class TestCharacters:
    async def test_preset_crud_and_cross_user_404(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
    ) -> None:
        t = await _register(client, register_user)
        _, ep = await _seed_episode(client, t)
        # 建预置角色
        cid = (
            await client.post(
                f"/api/episodes/{ep}/characters",
                json={"name": "小明", "role_type": "主角"},
                headers=_auth(t),
            )
        ).json()["data"]["id"]
        got = (await client.get(f"/api/episodes/{ep}/characters/{cid}", headers=_auth(t))).json()[
            "data"
        ]
        assert got["name"] == "小明" and got["source"] == "preset"
        # 更新 + 列表
        assert (
            await client.put(
                f"/api/episodes/{ep}/characters/{cid}",
                json={"persona": "热血少年"},
                headers=_auth(t),
            )
        ).status_code == 200
        chars = (await client.get(f"/api/episodes/{ep}/characters", headers=_auth(t))).json()[
            "data"
        ]
        assert len(chars) == 1
        # 删除
        assert (
            await client.delete(f"/api/episodes/{ep}/characters/{cid}", headers=_auth(t))
        ).status_code == 204

        # 跨用户 404(嵌套资源不泄露)
        t2 = await _register(client, register_user)
        assert (
            await client.get(f"/api/episodes/{ep}/characters", headers=_auth(t2))
        ).status_code == 404


class TestAnalyzeGates:
    async def test_no_config_is_409_and_no_script_is_422(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(llm_factory, "build", lambda snap, key: _RoutingTextModel())
        t = await _register(client, register_user)
        _, ep = await _seed_episode(client, t)
        # 有剧本、无 active 配置 → 409 model_not_configured
        resp = await client.post(f"/api/episodes/{ep}/analyze", headers=_auth(t))
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "model_not_configured"

        # 建配置;另起一剧集不写剧本 → 422 script_required
        await _create_text_config(client, t)
        did = (await client.post("/api/dramas", json={"name": "d2"}, headers=_auth(t))).json()[
            "data"
        ]["id"]
        ep2 = (
            await client.post(
                f"/api/dramas/{did}/episodes",
                json={"title": "e2", "aspect_ratio": "16:9"},
                headers=_auth(t),
            )
        ).json()["data"]["id"]
        resp = await client.post(f"/api/episodes/{ep2}/analyze", headers=_auth(t))
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "script_required"

    async def test_inflight_is_409(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 闸门未置位 → 首个拆解卡在 work(在途)→ 第二个 409 invalid_state
        gate = asyncio.Event()
        monkeypatch.setattr(llm_factory, "build", lambda snap, key: _RoutingTextModel(gate=gate))
        t = await _register(client, register_user)
        await _create_text_config(client, t)
        _, ep = await _seed_episode(client, t)
        first = await client.post(f"/api/episodes/{ep}/analyze", headers=_auth(t))
        assert first.status_code == 202
        second = await client.post(f"/api/episodes/{ep}/analyze", headers=_auth(t))
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "invalid_state"
        # 释放闸门让首个跑完(避免执行器收尾时仍有卡住协程)
        gate.set()
        await _poll_task(client, t, first.json()["data"]["id"])


class TestAnalyzePipeline:
    async def test_full_pipeline_then_shots_and_cancel(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(llm_factory, "build", lambda snap, key: _RoutingTextModel())
        t = await _register(client, register_user)
        await _create_text_config(client, t)
        _, ep = await _seed_episode(client, t)
        # 预置角色「小明」(分镜 appearing 经 name→id 解析到此)
        await client.post(
            f"/api/episodes/{ep}/characters",
            json={"name": "小明", "role_type": "主角"},
            headers=_auth(t),
        )

        task = await _run_analyze(client, t, ep)
        assert task["status"] == "succeeded"
        assert task["output_refs"]["analysis_id"]  # 产物引用回填

        # 双语义读:current 非空、无在途、未过期
        summary = (await client.get(f"/api/episodes/{ep}/analysis", headers=_auth(t))).json()[
            "data"
        ]
        assert summary["current_analysis"] is not None
        assert summary["current_analysis"]["status"] == "succeeded"
        assert summary["inflight_task"] is None
        assert summary["stale_flag"] is False

        # 分镜 + 出场角色回填
        shots = (await client.get(f"/api/episodes/{ep}/shots", headers=_auth(t))).json()["data"]
        assert len(shots) == 1
        assert shots[0]["appearing"][0]["name"] == "小明"

        # cancel 路径:闸门卡住新拆解 → 取消 → canceled → 重发放行
        gate = asyncio.Event()
        monkeypatch.setattr(llm_factory, "build", lambda snap, key: _RoutingTextModel(gate=gate))
        resp = await client.post(f"/api/episodes/{ep}/analyze", headers=_auth(t))
        assert resp.status_code == 202
        cancel = await client.post(
            f"/api/tasks/{resp.json()['data']['id']}/cancel", headers=_auth(t)
        )
        assert cancel.status_code == 200
        canceled = await _poll_task(client, t, resp.json()["data"]["id"])
        assert canceled["status"] == "canceled"
        # 重发:被取消的 analysis 标 failed(清 has_inflight)→ 放行
        gate.set()  # 恢复瞬时(下一个 analyze 用 gate,但已置位 → 不卡)
        rerun = await _run_analyze(client, t, ep)
        assert rerun["status"] == "succeeded"


class TestAnalysisHistory:
    async def test_history_new_to_old_and_cross_user_404(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(llm_factory, "build", lambda snap, key: _RoutingTextModel())
        t = await _register(client, register_user)
        await _create_text_config(client, t)
        _, ep = await _seed_episode(client, t)

        # 首次拆解 → 历史仅 1 条
        first = await _run_analyze(client, t, ep)
        assert first["status"] == "succeeded"
        hist = (await client.get(f"/api/episodes/{ep}/analyses", headers=_auth(t))).json()["data"]
        assert len(hist) == 1
        assert hist[0]["status"] == "succeeded"
        first_id = hist[0]["id"]

        # 重拆 → 历史 2 条,新→旧序;旧 analysis 保留可切回(D11)
        second = await _run_analyze(client, t, ep)
        assert second["status"] == "succeeded"
        hist = (await client.get(f"/api/episodes/{ep}/analyses", headers=_auth(t))).json()["data"]
        assert len(hist) == 2
        assert hist[0]["id"] == second["output_refs"]["analysis_id"]
        assert hist[1]["id"] == first_id  # 旧的排第二,append-only 保留

        # 跨用户:他人看不到此剧集的分析历史(404,不泄露存在)
        t2 = await _register(client, register_user)
        assert (
            await client.get(f"/api/episodes/{ep}/analyses", headers=_auth(t2))
        ).status_code == 404


class TestOptimizePipeline:
    async def test_optimize_produces_version_without_moving_pointer(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(llm_factory, "build", lambda snap, key: _RoutingTextModel())
        t = await _register(client, register_user)
        await _create_text_config(client, t)
        _, ep = await _seed_episode(client, t)

        # 指针在 input 版本
        before_versions = (
            await client.get(f"/api/episodes/{ep}/script/versions", headers=_auth(t))
        ).json()["data"]
        assert len(before_versions) == 1 and before_versions[0]["source"] == "input"

        resp = await client.post(f"/api/episodes/{ep}/script/optimize", headers=_auth(t))
        assert resp.status_code == 202
        task = await _poll_task(client, t, resp.json()["data"]["id"])
        assert task["status"] == "succeeded"
        out = task["output_refs"]
        assert out["version_id"]
        assert isinstance(out["diff"], list) and out["diff"]  # 段落级 diff 非空

        # 新增一个 optimize 版本;current 指针仍指 input(未移动)
        after_versions = (
            await client.get(f"/api/episodes/{ep}/script/versions", headers=_auth(t))
        ).json()["data"]
        assert len(after_versions) == 2
        opt = next(v for v in after_versions if v["source"] == "optimize")
        assert opt["id"] == out["version_id"]
        # 采纳 optimize 版本(select)→ 指针移动
        sel = (
            await client.post(
                f"/api/episodes/{ep}/script/versions/{opt['id']}/select",
                headers=_auth(t),
            )
        ).json()["data"]
        assert sel["id"] == opt["id"]

    async def test_inflight_query_returns_running_then_null(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 每次「进入剧本 tab 查在途 optimize 任务」端点:运行中返回该 task,完成 / 无则 null。
        gate = asyncio.Event()
        monkeypatch.setattr(llm_factory, "build", lambda snap, key: _RoutingTextModel(gate=gate))
        t = await _register(client, register_user)
        await _create_text_config(client, t)
        _, ep = await _seed_episode(client, t)

        # 尚无任何 optimize 任务 → 200 data=null(正常态,非 404)。
        r = await client.get(f"/api/episodes/{ep}/tasks/inflight?type=optimize", headers=_auth(t))
        assert r.status_code == 200 and r.json()["data"] is None

        # 发起优化;gate 未置 → 任务可观测地卡在 pending/running。
        resp = await client.post(f"/api/episodes/{ep}/script/optimize", headers=_auth(t))
        assert resp.status_code == 202
        task_id = resp.json()["data"]["id"]

        inflight = await client.get(
            f"/api/episodes/{ep}/tasks/inflight?type=optimize", headers=_auth(t)
        )
        assert inflight.status_code == 200
        data = inflight.json()["data"]
        assert data["id"] == task_id
        assert data["type"] == "optimize"
        assert data["status"] in ("pending", "running")

        # 释放 gate → 任务成功;终态任务不再是 in-flight → data=null。
        gate.set()
        await _poll_task(client, t, task_id)
        done = await client.get(
            f"/api/episodes/{ep}/tasks/inflight?type=optimize", headers=_auth(t)
        )
        assert done.status_code == 200 and done.json()["data"] is None

        # 非法 type → 422(Literal["analyze","optimize"] 校验)。
        bad = await client.get(f"/api/episodes/{ep}/tasks/inflight?type=render", headers=_auth(t))
        assert bad.status_code == 422

        # 跨用户:他人查此剧集 → 404(与其它剧集端点一致,不泄露存在)。
        t2 = await _register(client, register_user)
        xuser = await client.get(
            f"/api/episodes/{ep}/tasks/inflight?type=optimize", headers=_auth(t2)
        )
        assert xuser.status_code == 404


class TestShotsEdits:
    async def test_patch_split_merge_reorder_and_appearing(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(llm_factory, "build", lambda snap, key: _RoutingTextModel())
        t = await _register(client, register_user)
        await _create_text_config(client, t)
        _, ep = await _seed_episode(client, t)
        ming = (
            await client.post(
                f"/api/episodes/{ep}/characters",
                json={"name": "小明"},
                headers=_auth(t),
            )
        ).json()["data"]["id"]
        await _run_analyze(client, t, ep)
        shots = (await client.get(f"/api/episodes/{ep}/shots", headers=_auth(t))).json()["data"]
        sid = shots[0]["id"]

        # patch:改字段 + 替换出场 + 越界 warning(target_duration=1.0 < 3)
        r = (
            await client.patch(
                f"/api/shots/{sid}",
                json={"target_duration": 1.0, "appearing": [ming]},
                headers=_auth(t),
            )
        ).json()["data"]
        assert r["shot"]["target_duration"] == 1.0
        assert r["shot"]["appearing"][0]["episode_character_id"] == ming
        assert r["warnings"][0]["issue"] == "too_short"

        # split:插入新镜 → 2 条;seq 无空洞
        new = (
            await client.post(
                f"/api/shots/{sid}/split",
                json={"description": "新镜"},
                headers=_auth(t),
            )
        ).json()["data"]
        assert new["shot"]["description"] == "新镜"
        after_split = (await client.get(f"/api/episodes/{ep}/shots", headers=_auth(t))).json()[
            "data"
        ]
        assert [s["seq"] for s in after_split] == [1, 2]

        # merge:合并相邻 → 回到 1 条
        merged = (
            await client.post(
                f"/api/shots/{new['shot']['id']}/merge",
                json={"into_shot_id": sid},
                headers=_auth(t),
            )
        ).json()["data"]
        assert "新镜" in merged["shot"]["description"]
        assert (
            len((await client.get(f"/api/episodes/{ep}/shots", headers=_auth(t))).json()["data"])
            == 1
        )

        # 跨用户 404
        t2 = await _register(client, register_user)
        assert (
            await client.patch(f"/api/shots/{sid}", json={"description": "x"}, headers=_auth(t2))
        ).status_code == 404


class TestTasks:
    async def test_get_cross_user_404_and_cancel_terminal_409(
        self,
        client: AsyncClient,
        register_user: RegisterUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(llm_factory, "build", lambda snap, key: _RoutingTextModel())
        t = await _register(client, register_user)
        await _create_text_config(client, t)
        _, ep = await _seed_episode(client, t)
        task = await _run_analyze(client, t, ep)
        assert task["status"] == "succeeded"
        tid = task["id"]

        # 跨用户 GET → 404
        t2 = await _register(client, register_user)
        assert (await client.get(f"/api/tasks/{tid}", headers=_auth(t2))).status_code == 404
        # 已终态(succeeded)→ cancel 409 invalid_state
        cancel = await client.post(f"/api/tasks/{tid}/cancel", headers=_auth(t))
        assert cancel.status_code == 409
        assert cancel.json()["error"]["code"] == "invalid_state"
