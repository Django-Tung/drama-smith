"""API Key 信封加密原语(`design.md` D1,裁定 A2+m2)。

每条模型配置一个随机 DEK(32B):DEK 经 AES-256-GCM 加密明文 API Key,
DEK 本身经 MEK 加密封存。两层密文均为**自包含 blob** = `nonce(12) ‖ ct ‖ tag(16)`,
故只需两列(`api_key_ciphertext` / `dek_ciphertext`),无单独 IV 列(删除 `api_key_iv`)。
MEK 经 `core.config.get_mek()` 注入;明文 / DEK / MEK 均不入库 / 日志 / OpenAPI。

> 列布局裁定(A2):原 [`database.md §3.2`](../../../../../docs/tech-solution/database.md) 三列中
> DEK 层 nonce 无家可归,字面实现 `decrypt` 必败;两层对称自包含 blob 既修正该缝隙,
> 又与 KMS 信封惯例一致、少一条代码路径。脱敏串 `api_key_masked` 写时落库(m2),读路径不碰 MEK。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12  # GCM 推荐 96-bit(12B)nonce


@dataclass(frozen=True, slots=True)
class Envelope:
    """信封加密产物:两个自包含 blob(各为 `nonce ‖ ct ‖ tag`)。

    - `key_blob`:DEK 加密明文 API Key 的密文 → 落 `api_key_ciphertext`
    - `dek_blob`:MEK 加密 DEK 的密文(信封)→ 落 `dek_ciphertext`
    """

    key_blob: bytes
    dek_blob: bytes


def _seal(key: bytes, data: bytes) -> bytes:
    """AES-256-GCM 加密,返回自包含 blob `nonce ‖ ct ‖ tag`。

    `AESGCM.encrypt` 返回 `ct ‖ tag(16)`;nonce 由调用方生成并前置,解密时拆出。
    """
    nonce = os.urandom(_NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, data, None)


def _open(key: bytes, blob: bytes) -> bytes:
    """`_seal` 的逆:拆出 12B nonce 后解密(验 tag,失败抛 `cryptography.InvalidTag`)。"""
    nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ct, None)


def encrypt(plaintext: str, mek: bytes) -> Envelope:
    """生成新 DEK 并双层封存明文 API Key。

    新建 / 换 key(D8 全量重封)调用:每次产生新 DEK + 两层新 nonce。
    """
    dek = os.urandom(32)
    return Envelope(key_blob=_seal(dek, plaintext.encode()), dek_blob=_seal(mek, dek))


def decrypt(env: Envelope, mek: bytes) -> str:
    """MEK 解 DEK、DEK 解明文;仅驻内存,不落日志。"""
    dek = _open(mek, env.dek_blob)
    return _open(dek, env.key_blob).decode()


def mask_key(key: str) -> str:
    """脱敏:前缀 3 + 末 4 位(如 `sk-…ab12`)。

    过短的 key(< 8 位,无法既露首尾又不泄整串)一律回退为 `…`,避免泄露全串。
    """
    if len(key) < 8:
        return "…"
    return f"{key[:3]}…{key[-4:]}"
