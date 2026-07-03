"""LLM 接缝测试替身:确定性输出、可控 probe 成败(承接 backend.md §11)。

service 层测试(group 6)用这些替身驱动 probe 三态(成功 / `ProviderAuthFailed` /
`RateLimited` / `ProbeNotSupported`),不触真实网络。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class FakeTextModel:
    """`TextModel` 替身:`probe()` 按 `probe_raises` 抛错或静默;`chat()` 回放固定输出。"""

    def __init__(
        self,
        *,
        probe_raises: type[Exception] | None = None,
        output: str = "fake-text",
    ) -> None:
        self.probe_raises = probe_raises
        self.output = output
        self.probed = False

    async def chat(self, messages: Sequence[Mapping[str, str]], **params: Any) -> str:
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
