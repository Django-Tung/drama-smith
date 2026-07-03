"""供应商无关 LLM 接缝(`design.md` D5)。"""

from drama_smith.llm.base import (
    IMAGE_PROVIDERS,
    TEXT_PROVIDERS,
    VIDEO_PROVIDERS,
    ModelConfigSnapshot,
    ProbeNotSupported,
    validate_provider,
)
from drama_smith.llm.factory import build

__all__ = [
    "IMAGE_PROVIDERS",
    "TEXT_PROVIDERS",
    "VIDEO_PROVIDERS",
    "ModelConfigSnapshot",
    "ProbeNotSupported",
    "build",
    "validate_provider",
]
