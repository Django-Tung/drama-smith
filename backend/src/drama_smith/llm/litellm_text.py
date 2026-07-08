"""OpenAI 兼容文本适配器(litellm)。

`probe()` 经 `/models` 零成本探测(自检);`chat()` 为 M2 真实补全,经 `**params` 透传
`response_format` / tool-calling 等(**接缝仍返回 `str`,结构化解析归 `analysis/` 层**,D2)。
litellm 异常映射为 domain 错误并带**有界指数退避重试**(仅限可恢复错误,D8):
- `AuthenticationError`(401/403)→ `ProviderAuthFailed`(**不重试**,运行期置 invalid);
- `RateLimitError`/`Timeout`/`APIConnectionError` 与 429/5xx → `RateLimited`(重试,耗尽后抛);
- 其余 4xx → 原样上浮(请求格式错,调用方映射为任务 failed)。
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import litellm
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    RateLimitError,
    Timeout,
)

from drama_smith.core.errors import ProviderAuthFailed, RateLimited
from drama_smith.llm._probe import probe_models_endpoint
from drama_smith.llm.base import ModelConfigSnapshot, normalize_base_url

# 有界重试(D8):1 次首发 + 3 次重试,指数退避 1s/2s/4s。测试经 monkeypatch 缩短。
_MAX_RETRIES = 3
_BASE_DELAY = 1.0


class LitellmTextModel:
    """`TextModel` 实现:text 经 litellm;明文 Key 仅驻实例内存。"""

    def __init__(self, snapshot: ModelConfigSnapshot, api_key: str) -> None:
        self._snapshot = snapshot
        self._api_key = api_key
        # 规整 base_url(用户常填完整端点 …/v1/chat/completions → …/v1);chat 与 probe 共用。
        self._base_url = normalize_base_url(snapshot.base_url)

    async def chat(self, messages: Sequence[Mapping[str, str]], **params: Any) -> str:
        kwargs: dict[str, Any] = {
            "model": self._snapshot.model,
            "messages": list(messages),
            "api_key": self._api_key,
        }
        if self._base_url:
            # 自定义 base_url = OpenAI 兼容端点(SiliconFlow / Together 托管的 deepseek 等)。
            # 显式按 openai 路由,否则 litellm 对陌生模型串报 "LLM Provider NOT provided"
            # (5.5 spike 复现并验证)。原生 provider(无 base_url)仍由 litellm 按 model 路由。
            kwargs["api_base"] = self._base_url
            kwargs["custom_llm_provider"] = "openai"
        kwargs.update(params)  # 透传 response_format / temperature / max_tokens 等

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await litellm.acompletion(**kwargs)
                return str(resp.choices[0].message.content)
            except AuthenticationError as exc:
                # 鉴权失败:不可恢复,不重试(service 置 model_configs.status=invalid)。
                raise ProviderAuthFailed() from exc
            except (RateLimitError, Timeout, APIConnectionError) as exc:
                last_exc = exc
            except APIError as exc:
                status = getattr(exc, "status_code", None)
                if status in (401, 403):
                    raise ProviderAuthFailed() from exc
                if not (status == 429 or (isinstance(status, int) and status >= 500)):
                    raise  # 其余 4xx(如 400):请求格式错,不重试,上浮由调用方映射
                last_exc = exc
            # 可重试路径:未耗尽则退避后重试,耗尽则落到末尾统一抛 `RateLimited`。
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_BASE_DELAY * (2**attempt))
        raise RateLimited(f"Provider unavailable after {_MAX_RETRIES + 1} attempts") from last_exc

    async def probe(self) -> None:
        await probe_models_endpoint(self._base_url, self._api_key, provider=self._snapshot.provider)
