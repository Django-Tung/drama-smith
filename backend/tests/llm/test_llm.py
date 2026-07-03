"""LLM 接缝单测:供应商白名单校验(D12)、factory 路由(D5)、零成本探测状态映射(D6)。"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from drama_smith.core.errors import ProviderAuthFailed, RateLimited
from drama_smith.llm import ModelConfigSnapshot, ProbeNotSupported, validate_provider
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
