"""按 purpose 构造模型接缝实例(`design.md` D5)。

`build(snapshot, plaintext_key)`:text/image → litellm 适配,video → 自定义适配器(M3 占位)。
明文 Key 由 service 解密后传入,本层不 import crypto(分层自检,任务 5.7)。
"""

from __future__ import annotations

from drama_smith.llm.adapters import build_video_adapter
from drama_smith.llm.base import ImageModel, ModelConfigSnapshot, TextModel, VideoModel
from drama_smith.llm.litellm_image import LitellmImageModel
from drama_smith.llm.litellm_text import LitellmTextModel


def build(snapshot: ModelConfigSnapshot, plaintext_key: str) -> TextModel | ImageModel | VideoModel:
    """构造接缝实例。构造时明文 Key 仅驻返回对象的内存,不落库/日志。"""
    if snapshot.purpose == "text":
        return LitellmTextModel(snapshot, plaintext_key)
    if snapshot.purpose == "image":
        return LitellmImageModel(snapshot, plaintext_key)
    return build_video_adapter(snapshot, plaintext_key)
