"""测试辅助:跨用例共享的纯函数与类型别名(非夹具)。"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

# `register_user` 夹具的调用类型(供用例签名标注,满足 mypy strict)。
RegisterUser = Callable[..., Awaitable[dict[str, Any]]]


def unique_username(prefix: str = "user") -> str:
    """生成系统内唯一的测试用户名(3–32 位字母数字下划线)。"""
    return f"{prefix}_{uuid.uuid4().hex[:20]}"
