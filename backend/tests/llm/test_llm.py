"""LLM 接缝单测:供应商白名单校验(D12)、factory 路由(D5)、零成本探测状态映射(D6)。"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx
import litellm
import pytest
from litellm.exceptions import AuthenticationError, RateLimitError

from drama_smith.core.errors import ProviderAuthFailed, RateLimited
from drama_smith.llm import ModelConfigSnapshot, ProbeNotSupported, litellm_text, validate_provider
from drama_smith.llm._probe import probe_models_endpoint
from drama_smith.llm.base import (
    IMAGE_PROVIDERS,
    TEXT_PROVIDERS,
    VIDEO_PROVIDERS,
    ImageModel,
    TextModel,
)
from drama_smith.llm.factory import build
from drama_smith.llm.litellm_image import LitellmImageModel
from drama_smith.llm.litellm_text import LitellmTextModel


def _snap(purpose: str, provider: str) -> ModelConfigSnapshot:
    return ModelConfigSnapshot(purpose=purpose, provider=provider, model="m")


# ---- 白名单校验(D12)----
@pytest.mark.parametrize(
    ("purpose", "provider"),
    [
        ("text", "openai"),
        ("text", "zhipu"),
        ("text", "anthropic"),
        ("image", "seedream"),
        ("image", "openai"),
        ("video", "seedance"),
        ("video", "kling"),
    ],
)
def test_validate_provider_accepts_whitelisted(purpose: str, provider: str) -> None:
    validate_provider(purpose, provider)  # 不抛即通过


def test_validate_provider_rejects_provider_not_in_purpose() -> None:
    # seedream 是 image-only,放进 text 应被拒
    with pytest.raises(ValueError, match="not supported for purpose"):
        validate_provider("text", "seedream")


def test_validate_provider_rejects_unknown_purpose() -> None:
    with pytest.raises(ValueError, match="Unknown purpose"):
        validate_provider("audio", "openai")


def test_whitelists_match_first_run_set() -> None:
    assert {"openai", "zhipu", "deepseek"} <= TEXT_PROVIDERS
    assert {"seedream", "wanx", "cogview"} <= IMAGE_PROVIDERS
    assert {"seedance", "kling", "veo"} <= VIDEO_PROVIDERS


# ---- factory 路由(D5)----
def test_build_text_returns_litellm_text() -> None:
    model = build(_snap("text", "openai"), "plain-key")
    assert isinstance(model, LitellmTextModel)
    assert isinstance(model, TextModel)


def test_build_image_returns_litellm_image() -> None:
    model = build(_snap("image", "seedream"), "plain-key")
    assert isinstance(model, LitellmImageModel)
    assert isinstance(model, ImageModel)


def test_build_video_raises_not_implemented() -> None:
    # video 首发「列但不实现」(M3 占位)
    with pytest.raises(NotImplementedError, match="M3"):
        build(_snap("video", "kling"), "plain-key")


# ---- 零成本探测 /models 状态映射(D6)----
async def _probe_with(handler: Callable[[httpx.Request], httpx.Response]) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await probe_models_endpoint("https://api.test/v1", "k", provider="openai", client=client)
    finally:
        await client.aclose()


async def test_probe_ok_on_2xx() -> None:
    await _probe_with(lambda req: httpx.Response(200))


async def test_probe_auth_fail_on_401() -> None:
    with pytest.raises(ProviderAuthFailed):
        await _probe_with(lambda req: httpx.Response(401))


async def test_probe_auth_fail_on_403() -> None:
    with pytest.raises(ProviderAuthFailed):
        await _probe_with(lambda req: httpx.Response(403))


async def test_probe_rate_limited_on_429() -> None:
    with pytest.raises(RateLimited):
        await _probe_with(lambda req: httpx.Response(429))


async def test_probe_rate_limited_on_5xx() -> None:
    with pytest.raises(RateLimited):
        await _probe_with(lambda req: httpx.Response(503))


async def test_probe_not_supported_on_404() -> None:
    with pytest.raises(ProbeNotSupported):
        await _probe_with(lambda req: httpx.Response(404))


async def test_probe_rate_limited_on_timeout() -> None:
    def _timeout(_req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    with pytest.raises(RateLimited):
        await _probe_with(_timeout)


# ---- chat() 映射 + 有界重试(D8)----
def _resp(content: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class TestLitellmChat:
    """鉴权失败不重试、限流/超时重试、response_format 透传、耗尽后 RateLimited。"""

    async def test_returns_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake(**kwargs: Any) -> SimpleNamespace:
            return _resp("hello")

        monkeypatch.setattr(litellm, "acompletion", fake)
        monkeypatch.setattr(litellm_text, "_BASE_DELAY", 0.0)
        model = LitellmTextModel(_snap("text", "openai"), "k")
        assert await model.chat([{"role": "user", "content": "hi"}]) == "hello"

    async def test_transmits_response_format_and_params(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        async def fake(**kwargs: Any) -> SimpleNamespace:
            captured.update(kwargs)
            return _resp()

        monkeypatch.setattr(litellm, "acompletion", fake)
        monkeypatch.setattr(litellm_text, "_BASE_DELAY", 0.0)
        model = LitellmTextModel(_snap("text", "openai"), "k")
        await model.chat(
            [{"role": "user", "content": "hi"}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        assert captured["response_format"] == {"type": "json_object"}
        assert captured["temperature"] == 0.2
        assert captured["model"] == "m"

    async def test_auth_failure_not_retried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        async def fake(**kwargs: Any) -> SimpleNamespace:
            calls["n"] += 1
            raise AuthenticationError("bad key", "gpt-4o-mini", "openai")

        monkeypatch.setattr(litellm, "acompletion", fake)
        monkeypatch.setattr(litellm_text, "_BASE_DELAY", 0.0)
        model = LitellmTextModel(_snap("text", "openai"), "k")
        with pytest.raises(ProviderAuthFailed):
            await model.chat([{"role": "user", "content": "hi"}])
        assert calls["n"] == 1  # 鉴权失败立即抛,不重试

    async def test_rate_limit_retries_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(litellm_text, "_MAX_RETRIES", 3)
        monkeypatch.setattr(litellm_text, "_BASE_DELAY", 0.0)
        calls = {"n": 0}

        async def fake(**kwargs: Any) -> SimpleNamespace:
            calls["n"] += 1
            if calls["n"] < 3:
                raise RateLimitError("slow down", "gpt-4o-mini", "openai")
            return _resp("ok")

        monkeypatch.setattr(litellm, "acompletion", fake)
        model = LitellmTextModel(_snap("text", "openai"), "k")
        assert await model.chat([{"role": "user", "content": "hi"}]) == "ok"
        assert calls["n"] == 3

    async def test_rate_limit_exhausted_raises_rate_limited(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(litellm_text, "_MAX_RETRIES", 2)
        monkeypatch.setattr(litellm_text, "_BASE_DELAY", 0.0)
        calls = {"n": 0}

        async def fake(**kwargs: Any) -> SimpleNamespace:
            calls["n"] += 1
            raise RateLimitError("slow", "gpt-4o-mini", "openai")

        monkeypatch.setattr(litellm, "acompletion", fake)
        model = LitellmTextModel(_snap("text", "openai"), "k")
        with pytest.raises(RateLimited):
            await model.chat([{"role": "user", "content": "hi"}])
        assert calls["n"] == 3  # 1 首发 + 2 重试
