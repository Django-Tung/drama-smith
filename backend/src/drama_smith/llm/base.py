"""供应商无关 LLM 接缝:Protocols + 供应商白名单 + 配置快照。

设计依据(`design.md` D5/D6/D12、`backend.md` §6):
- 三类 Protocol:`TextModel`(chat)、`ImageModel`(generate)、`VideoModel`(submit+poll,异步)。
- **本期(M1)仅 `probe()` 被自检调用**;chat/generate(M2)、submit/poll(M3)为接缝完整性声明。
- 供应商白名单(D12,首发清单):见 `docs/requirements/features/ai-config.md` §2.1。
- 本模块保持「不 import crypto/services/graphs」(分层自检,任务 5.7):明文 Key 由 service 解密后注入。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

# ---- 供应商白名单(D12,首发清单,ai-config §2.1)----
TEXT_PROVIDERS: frozenset[str] = frozenset(
    {
        "openai",
        "anthropic",
        "gemini",
        "zhipu",
        "deepseek",
        "moonshot",
        "qwen",
        "doubao",
        "xai",
    }
)
IMAGE_PROVIDERS: frozenset[str] = frozenset(
    {
        "openai",
        "seedream",
        "wanx",
        "cogview",
        "flux",
        "stability",
        "ideogram",
    }
)
# video 首发「列但不实现」:本期仅占位,M3 落具体异步适配器。
VIDEO_PROVIDERS: frozenset[str] = frozenset(
    {
        "seedance",
        "kling",
        "veo",
        "wan",
        "minimax",
        "runway",
        "pika",
        "luma",
        "sora",
    }
)

_PROVIDERS_BY_PURPOSE: dict[str, frozenset[str]] = {
    "text": TEXT_PROVIDERS,
    "image": IMAGE_PROVIDERS,
    "video": VIDEO_PROVIDERS,
}

# 未显式给 base_url 时的 OpenAI 兼容默认 endpoint(仅 openai 自身可靠;其余 provider 需 base_url)。
_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


def normalize_base_url(url: str | None) -> str | None:
    """规整自定义 base_url,供 litellm 接缝统一使用。

    用户在 BYOK 里常填**完整端点**(如 `…/v1/chat/completions`),而 litellm 只要 base
    (`…/v1`,自己拼 `/chat/completions`)。此处去尾 `/chat/completions` 与多余斜杠;`None` 透传。
    同时让零成本探测拼出的 `/models` 落在正确路径(否则打到 `…/chat/completions/models` 误报)。
    """
    if url is None:
        return None
    cleaned = url.strip().rstrip("/")  # 先去尾斜杠,使 /chat/completions/ 也能识别
    if cleaned.endswith("/chat/completions"):
        cleaned = cleaned[: -len("/chat/completions")]
    return cleaned or None


_VALID_PURPOSES = frozenset(_PROVIDERS_BY_PURPOSE)


def validate_provider(purpose: str, provider: str) -> None:
    """校验 `(purpose, provider)` ∈ 白名单;越界 → `ValueError`(供 schema/API 层映射 422,D12)。"""
    if purpose not in _VALID_PURPOSES:
        msg = f"Unknown purpose: {purpose!r}"
        raise ValueError(msg)
    if provider not in _PROVIDERS_BY_PURPOSE[purpose]:
        msg = f"Provider {provider!r} is not supported for purpose {purpose!r}"
        raise ValueError(msg)


class ProbeNotSupported(Exception):
    """该 provider 无零成本探测路径(D6 降级:service 跳过并显式告知,非错误)。"""


@dataclass(frozen=True, slots=True)
class ModelConfigSnapshot:
    """构造模型接缝所需的配置快照(由 service 从 `ModelConfig` + 解密 Key 组装)。

    明文 API Key 不在此(由 factory/adapters 单独持有,仅驻内存);本快照只含「如何调用」元信息。
    """

    purpose: str
    provider: str
    model: str
    base_url: str | None = None
    params: dict[str, Any] | None = None
    provider_options: dict[str, Any] | None = None


@runtime_checkable
class TextModel(Protocol):
    """文本模型接缝。`probe()` 零成本自检(本期唯一调用点);`chat()` 真实补全(M2)。"""

    async def chat(self, messages: Sequence[Mapping[str, str]], **params: Any) -> str: ...
    async def probe(self) -> None: ...


@runtime_checkable
class ImageModel(Protocol):
    """图片模型接缝。`probe()` 零成本自检;`generate()` 真实生成(M2)。"""

    async def generate(self, prompt: str, **params: Any) -> str: ...
    async def probe(self) -> None: ...


@runtime_checkable
class VideoModel(Protocol):
    """视频模型接缝(异步 submit+poll;M3 落具体适配器,本期仅占位)。"""

    async def submit(self, prompt: str, **params: Any) -> str: ...
    async def poll(self, task_id: str) -> Any: ...
