"""OpenAI 兼容文本适配器(litellm)。

本期 `probe()` 经 `/models` 零成本探测(自检唯一调用点);`chat()` 为 M2 真实补全,
声明接缝完整性、本期不被调用。litellm 归一 OpenAI 兼容 provider 的鉴权与请求格式。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import litellm

from drama_smith.llm._probe import probe_models_endpoint
from drama_smith.llm.base import ModelConfigSnapshot


class LitellmTextModel:
    """`TextModel` 实现:text 经 litellm;明文 Key 仅驻实例内存。"""

    def __init__(self, snapshot: ModelConfigSnapshot, api_key: str) -> None:
        self._snapshot = snapshot
        self._api_key = api_key

    async def chat(self, messages: Sequence[Mapping[str, str]], **params: Any) -> str:
        # M2 真实调用;本期声明接缝完整性,自检不触发。
        kwargs: dict[str, Any] = {
            "model": self._snapshot.model,
            "messages": list(messages),
            "api_key": self._api_key,
        }
        if self._snapshot.base_url:
            kwargs["api_base"] = self._snapshot.base_url
        kwargs.update(params)
        resp = await litellm.acompletion(**kwargs)
        return str(resp.choices[0].message.content)

    async def probe(self) -> None:
        await probe_models_endpoint(
            self._snapshot.base_url, self._api_key, provider=self._snapshot.provider
        )
