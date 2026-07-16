"""富媒体字节存储抽象(`FileStore` Protocol;design D2 / backend.md §8)。

字节落外部存储(本期本地磁盘;预留对象存储接缝),元数据落 MySQL `media` 表。本 Protocol
只定义「存 / 读 / 删 / 签 / 验」五法;具体后端(`LocalFileStore`)在 `local.py`。`sign` /
`verify` 为鉴权签名 URL 的凭证签发与校验(`<img src>` 直用,免 Authorization header,D10)。

`storage/` 不属 NFR-2 的「不得 import litellm/crypto/services」目录(那些是 `analysis/`/`graphs/`
/`tasks/`);签名用 pyjwt 原语(jwt_secret 复用,不引新密钥)。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class FileStore(Protocol):
    """富媒体字节存储 + 签名 URL 凭证接缝。"""

    def save(self, *, user_id: int, data: bytes, ext: str) -> str:
        """持久化字节;返回 `storage_key`(后端内部相对路径,写入 `media.storage_key`)。

        `ext` 为规范化扩展名(无点,如 `jpg`);后端按 `<root>/<user_id>/<yyyy>/<mm>/<uuid>.<ext>`
        生成唯一路径。`user_id` 参与路径隔离(防跨用户扫盘)。
        """
        ...

    def read(self, storage_key: str) -> bytes:
        """按 `storage_key` 读回字节(内容端点流式下发用)。"""
        ...

    def delete(self, storage_key: str) -> None:
        """删除字节(best-effort;不存在不报错)。本期旧形象图保留不删(D9),预留清理用。"""
        ...

    def sign(self, media_id: int) -> tuple[str, int]:
        """为 `media_id` 签发短期凭证;返回 `(token, exp_unix)`。

        token = HS256(`{sub: media_id, exp}`, 用 `jwt_secret`);内容端点 `GET /api/media/:id/content`
        经 `verify` 校验后流式下发,`<img src>` 直用。
        """
        ...

    def verify(self, token: str, media_id: int) -> bool:
        """校验 token:签名有效 + `sub == media_id` + 未过期。任一不符返回 False(端点 → 401)。"""
        ...
