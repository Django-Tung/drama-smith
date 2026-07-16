"""OpenAI 兼容图片适配器(litellm)。

`probe()` 经 `/models` 零成本探测(自检);`generate()` 为 M3 真实生成(角色形象图异步任务),
经 `**params` 透传尺寸 / 风格等。范式与 `litellm_text.py` 对齐(M2 spike 修过的同款缺陷 + 异常映射
+ 有界重试,收尾原 `TODO(M3)`):
- 当 `snapshot.base_url` 给定时,显式 `custom_llm_provider="openai"` + `normalize_base_url`
  规整端点(否则 litellm 对陌生模型串报 "LLM Provider NOT provided");原生 provider(无 base_url)
  仍由 litellm 按 model 路由。
- `AuthenticationError`(401/403)→ `ProviderAuthFailed`(**不重试**,运行期置 `status=invalid`);
- `RateLimitError`/`Timeout`/`APIConnectionError` 与 429/5xx → 1+3 次指数退避(1s/2s/4s),耗尽抛
  `RateLimited`;
- 其余 4xx → 原样上浮(请求格式错,调用方映射为任务 failed)。
"""

from __future__ import annotations

import asyncio
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


class LitellmImageModel:
    """`ImageModel` 实现:image 经 litellm;明文 Key 仅驻实例内存。"""

    def __init__(self, snapshot: ModelConfigSnapshot, api_key: str) -> None:
        self._snapshot = snapshot
        self._api_key = api_key
        # 规整 base_url(用户常填完整端点 …/v1/images/generations → …/v1);generate 与 probe 共用。
        self._base_url = normalize_base_url(snapshot.base_url)

    async def generate(self, prompt: str, **params: Any) -> str:
        kwargs: dict[str, Any] = {
            "model": self._snapshot.model,
            "prompt": prompt,
            "api_key": self._api_key,
        }
        if self._base_url:
            # 自定义 base_url = OpenAI 兼容端点;显式按 openai 路由(与 litellm_text 同款,
            # 见 5.5 spike)。
            kwargs["api_base"] = self._base_url
            kwargs["custom_llm_provider"] = "openai"
        kwargs.update(params)  # 透传 size / quality / n 等

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await litellm.aimage_generation(**kwargs)
                return str(resp.data[0].url)
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
