"""`FileStore` 的本地磁盘实现(design D2 / backend.md §8)。

落盘 `<media_root>/<user_id>/<yyyy>/<mm>/<uuid>.<ext>`;`storage_key` 为相对 `media_root` 的
POSIX 路径(跨平台稳定,写入 `media.storage_key`)。签名 URL 用 pyjwt HS256(复用 `jwt_secret`,
**不引新密钥**),`<img src>` 直用、免 Authorization header(D10)。

单实例经 `main.lifespan` 构造注入 `app.state.file_store`;测试注入 `InMemoryFileStore` 替身
(`storage.base.FileStore` 为 `runtime_checkable Protocol`,鸭子类型即过 `isinstance`)。
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import jwt

_SEPARATOR = "/"  # storage_key 用 POSIX 分隔(跨平台稳定)


class LocalFileStore:
    """本地磁盘 FileStore:`save` 落盘 + `read`/`delete` + HS256 签名 URL。"""

    def __init__(self, media_root: str | Path, secret: str, ttl_seconds: int) -> None:
        self._root = Path(media_root)
        self._secret = secret
        self._ttl = ttl_seconds

    def ensure_root(self) -> None:
        """启动期创建根目录(lifespan 调用);缺失权限抛 OSError,fail-fast。"""
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, *, user_id: int, data: bytes, ext: str) -> str:
        """落盘;返回相对 `media_root` 的 POSIX `storage_key`。

        路径含 `user_id` 隔离 + 年月分桶(控单目录文件数);文件名用 uuid4 防碰撞与遍历。
        """
        now = datetime.now(UTC)
        rel = Path(str(user_id), f"{now:%Y}", f"{now:%m}", f"{uuid.uuid4().hex}.{ext}")
        path = self._root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        # 用 POSIX 分隔落库(读回时再 joinpath,跨平台一致)。
        return _SEPARATOR.join(rel.parts)

    def read(self, storage_key: str) -> bytes:
        path = self._root / Path(*storage_key.split(_SEPARATOR))
        return path.read_bytes()

    def delete(self, storage_key: str) -> None:
        path = self._root / Path(*storage_key.split(_SEPARATOR))
        with contextlib.suppress(FileNotFoundError):
            path.unlink()  # best-effort:旧文件可能已清,删不存在的 key 不报错(D9)

    def sign(self, media_id: int) -> tuple[str, int]:
        """HS256 签发短期凭证(`sub`=media_id, `exp`=now+ttl);返回 (token, exp_unix)。"""
        exp = int(datetime.now(UTC).timestamp()) + self._ttl
        token = jwt.encode({"sub": str(media_id), "exp": exp}, self._secret, algorithm="HS256")
        return token, exp

    def verify(self, token: str, media_id: int) -> bool:
        """校验 token:签名有效 + `sub == media_id` + 未过期;任一不符返回 False。"""
        try:
            claims = jwt.decode(token, self._secret, algorithms=["HS256"])
        except jwt.PyJWTError:
            return False
        return claims.get("sub") == str(media_id)


def build_signed_url(media_id: int, token: str, exp: int) -> str:
    """拼内容端点相对 URL(`<img src>` 直用;前端经 Vite 代理 / 生产反代打到后端)。

    `exp` 随附为查询参数供前端预判刷新(后端校验以 token 内嵌 exp 为准);路径与
    `api/media.py` 的 `GET /api/media/:media_id/content` 对齐。
    """
    return f"/api/media/{media_id}/content?token={token}&exp={exp}"
