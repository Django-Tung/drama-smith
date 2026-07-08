"""OpenAI 兼容图片适配器(litellm)。

本期 `probe()` 经 `/models` 零成本探测(自检唯一调用点);`generate()` 为 M2 真实生成,
声明接缝完整性、本期不被调用。

TODO(M3):`generate()` 给了 `base_url` 时同样需要 `custom_llm_provider="openai"` +
`normalize_base_url`(与 `litellm_text.py` 5.5 spike 修的同款缺陷);M2 不触达 image,
留待 M3 引入图片生成时一并修并补测。
"""

from __future__ import annotations

from typing import Any

import litellm

from drama_smith.llm._probe import probe_models_endpoint
from drama_smith.llm.base import ModelConfigSnapshot


class LitellmImageModel:
    """`ImageModel` 实现:image 经 litellm;明文 Key 仅驻实例内存。"""

    def __init__(self, snapshot: ModelConfigSnapshot, api_key: str) -> None:
        self._snapshot = snapshot
        self._api_key = api_key

    async def generate(self, prompt: str, **params: Any) -> str:
        # M2 真实调用;本期声明接缝完整性,自检不触发。
        kwargs: dict[str, Any] = {
            "model": self._snapshot.model,
            "prompt": prompt,
            "api_key": self._api_key,
        }
        if self._snapshot.base_url:
            kwargs["api_base"] = self._snapshot.base_url
        kwargs.update(params)
        resp = await litellm.aimage(**kwargs)
        return str(resp.data[0].url)

    async def probe(self) -> None:
        await probe_models_endpoint(
            self._snapshot.base_url, self._api_key, provider=self._snapshot.provider
        )
