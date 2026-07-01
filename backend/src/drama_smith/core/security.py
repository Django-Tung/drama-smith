"""安全原语:密码(argon2id)、JWT(HS256)、刷新令牌。

定位为纯原语层(`design.md` D15):模块级函数、不绑 settings、不耦合领域异常。

- `create_access_token` / `verify_access_token` 取 `secret` / `ttl` 作显式参数,
  由阶段四 `get_security` 依赖读 settings 后传入(便于阶段六单测)。
- 验签失败**抛 pyjwt 原生异常**(`ExpiredSignatureError` / `InvalidTokenError`),
  映射为 401 `unauthenticated` 在阶段四 `deps` 完成;本模块不 import `core/errors`。

参数选择见 `design.md` D16(argon2id)、D17(刷新令牌 sha256)、D18(JWT 细节)。
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError

# argon2id 默认参数(19 MiB / time_cost 2 / parallelism 1),RFC 推荐量级(D16)。
_password_hasher = PasswordHasher()

# 刷新令牌明文熵:256-bit;token_urlsafe → ~43 个 URL 安全字符。
_REFRESH_TOKEN_BYTES = 32

__all__ = [
    "create_access_token",
    "generate_refresh_token",
    "hash_password",
    "hash_refresh_token",
    "verify_access_token",
    "verify_password",
]


def hash_password(password: str) -> str:
    """argon2id 加盐哈希;返回含盐与参数的编码串(落库 `users.password_hash`)。"""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码。

    不匹配(`VerifyMismatchError`)或哈希格式错误(`InvalidHash`)均返回 `False`,
    一律按无效凭证处理(→ 401),不向调用方泄露解析错误;argon2 自带恒定时间比对。
    """
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHash):
        return False


def create_access_token(user_id: int, username: str, secret: str, ttl_seconds: int) -> str:
    """签发 HS256 access token;claims:`sub`(str)、`username`、`iat`、`exp`(均 UTC)。"""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),  # RFC 7519:sub 为字符串;还原用 int(claims["sub"])(D18)
        "username": username,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_access_token(token: str, secret: str) -> Mapping[str, Any]:
    """校验 HS256 access token,返回 claims。

    强制 `algorithms=["HS256"]`(D18,防 `alg=none` / 密钥混淆);过期或无效抛
    pyjwt 原生异常(`ExpiredSignatureError` / `InvalidTokenError`),由上层映射 401。
    时钟 leeway 由阶段四 deps 设置,本函数保持严格。
    """
    return jwt.decode(token, secret, algorithms=["HS256"])


def generate_refresh_token() -> str:
    """生成不透明刷新令牌明文(256-bit,URL-safe)。

    明文仅返回客户端一次,永不落库/日志(spec「never the plaintext」);服务端只存其哈希。
    """
    return secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """刷新令牌 SHA-256 哈希(快哈希;令牌已 256-bit 高熵不可猜,不用 argon2,D17)。

    确定性:同一明文 → 同一哈希,供按 `token_hash` 唯一索引查找,无字符串比对时序侧信道。
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
