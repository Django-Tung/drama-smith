"""LLM 接缝测试替身:确定性输出、可控 probe/chat 成败(承接 backend.md §11)。

service / analysis 层测试用这些替身驱动三态(成功 / `ProviderAuthFailed` / `RateLimited` /
`ProbeNotSupported`),不触真实网络。`chat_outcomes` 支持按调用顺序回放「值或异常」序列,
可模拟「先失败若干次再成功」以验证上层重试/恢复行为。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class FakeTextModel:
    """`TextModel` 替身。

    - `probe()` 按 `probe_raises` 抛错或静默;
    - `chat()` 默认回放 `output`;若给 `chat_outcomes`(list[str | Exception])则按调用顺序
      回放,异常实例会被抛出;超出长度时复用最后一项(模拟持续成功 / 持续失败)。
    """

    def __init__(
        self,
        *,
        probe_raises: type[Exception] | None = None,
        output: str = "fake-text",
        chat_outcomes: list[str | Exception] | None = None,
    ) -> None:
        self.probe_raises = probe_raises
        self.output = output
        self.chat_outcomes = chat_outcomes
        self.probed = False
        self.chat_calls = 0

    async def chat(self, messages: Sequence[Mapping[str, str]], **params: Any) -> str:
        self.chat_calls += 1
        if self.chat_outcomes is not None:
            idx = min(self.chat_calls - 1, len(self.chat_outcomes) - 1)
            outcome = self.chat_outcomes[idx]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return self.output

    async def probe(self) -> None:
        self.probed = True
        if self.probe_raises is not None:
            raise self.probe_raises("fake probe failure")


class FakeImageModel:
    """`ImageModel` 替身:`probe()` 按 `probe_raises` 抛错或静默;`generate()` 回放固定 URL。"""

    def __init__(
        self,
        *,
        probe_raises: type[Exception] | None = None,
        output: str = "https://fake.test/image.png",
    ) -> None:
        self.probe_raises = probe_raises
        self.output = output
        self.probed = False

    async def generate(self, prompt: str, **params: Any) -> str:
        return self.output

    async def probe(self) -> None:
        self.probed = True
        if self.probe_raises is not None:
            raise self.probe_raises("fake probe failure")
