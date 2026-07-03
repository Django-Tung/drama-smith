"""视频适配器抽象位(M3 首批接入,本期仅占位)。

视频供应商(Seedance/Kling/Veo/Wan/...)多为异步、协议差异大(见 architecture §4.2),
本期不实现具体调用。抽象为 `VideoModel` Protocol(在 `llm.base`);`build_video_adapter`
为「未实现占位」,M3 在此补 `adapters/<provider>.py`。
"""

from __future__ import annotations

from drama_smith.llm.base import ModelConfigSnapshot, VideoModel


def build_video_adapter(snapshot: ModelConfigSnapshot, api_key: str) -> VideoModel:
    """占位:M3 落具体视频适配器;本期调用即 `NotImplementedError`。"""
    raise NotImplementedError(
        f"Video adapter for provider {snapshot.provider!r} lands in M3"
    )
