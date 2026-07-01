"""应用层(services):用例编排 + 事务边界(`design.md` D14)。

依赖方向只向下:仅 import `core` / `db`,不反向依赖 `api`。
"""

from drama_smith.services import auth_service

__all__ = ["auth_service"]
