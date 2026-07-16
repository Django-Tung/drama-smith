"""富媒体字节存储(`FileStore` 抽象 + 本地实现;design D2 / backend.md §8)。"""

from drama_smith.storage.base import FileStore
from drama_smith.storage.local import LocalFileStore, build_signed_url

__all__ = ["FileStore", "LocalFileStore", "build_signed_url"]
