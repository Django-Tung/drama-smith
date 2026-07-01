"""认证用例编排(services / 应用层)。

事务边界在此(`design.md` D14):用例内显式 `commit`;异常时由请求级会话关闭回滚
(`get_session` 的 `async with` 退出 → `close` → 回滚未提交事务)。

- `register` / `login`:创建或更新用户 + 签发 access+refresh,提交。
- `refresh`:只读校验(哈希 / 未过期 / 未吊销)→ 签发新 access,无写库(spec 不轮换 refresh)。
- `logout`:按归属用户吊销 refresh,提交(越权 / 不存在 → `NotFound`)。

只向下依赖 `core` / `db`;令牌签发直接用 `core.security` 模块级原语(D15:security 保持纯原语)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.config import Settings
from drama_smith.core.errors import Locked, Unauthenticated
from drama_smith.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from drama_smith.db.base import utcnow
from drama_smith.db.models import User
from drama_smith.db.repositories import refresh_token_repo, user_repo


@dataclass(frozen=True, slots=True)
class AuthResult:
    """注册 / 登录用例结果:用户实体 + 一次性下发的令牌明文。"""

    user: User
    access_token: str
    refresh_token: str  # 明文,仅返回客户端一次;服务端只存哈希


def _access_token(user: User, settings: Settings) -> str:
    """按当前 settings 签发 access token(HS256;secret 取 SecretStr 值)。"""
    return create_access_token(
        user.id,
        user.username,
        settings.jwt_secret.get_secret_value(),
        settings.jwt_access_ttl_seconds,
    )


async def _issue_tokens(session: AsyncSession, user: User, settings: Settings) -> tuple[str, str]:
    """签发 access(JWT)与 refresh(随机串,落哈希);返回 (access, refresh 明文)。"""
    access_token = _access_token(user, settings)
    plain_refresh = generate_refresh_token()
    await refresh_token_repo.create(
        session,
        user_id=user.id,
        token_hash=hash_refresh_token(plain_refresh),
        expires_at=utcnow() + timedelta(days=settings.refresh_ttl_days),
    )
    return access_token, plain_refresh


async def register(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    settings: Settings,
) -> AuthResult:
    """注册:argon2id 落库(用户名冲突 → `Conflict`)+ 签发令牌 + 提交。"""
    user = await user_repo.create(session, username=username, password_hash=hash_password(password))
    access_token, plain_refresh = await _issue_tokens(session, user, settings)
    await session.commit()
    return AuthResult(user=user, access_token=access_token, refresh_token=plain_refresh)


async def login(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    settings: Settings,
) -> AuthResult:
    """登录:锁定检查 → 校验密码 → 失败递增 / 成功清零 + 签发令牌。

    - 账号不存在或密码错误 → `Unauthenticated`(不泄露存在性)。
    - 锁定期内 → `Locked`(即使密码正确)。
    - 锁已过期 → 自动解锁并重置计数(spec「Lock auto-expires → counter reset」)。
    """
    user = await user_repo.get_by_username(session, username)
    if user is None:
        raise Unauthenticated("Invalid username or password")

    now = utcnow()
    if user.locked_until is not None:
        if user.locked_until > now:
            raise Locked("Account is temporarily locked")
        user.locked_until = None
        user.failed_login_count = 0

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
        await session.commit()  # 持久化失败计数 / 锁定后,再返回错误
        raise Unauthenticated("Invalid username or password")

    user.failed_login_count = 0
    user.last_login_at = now
    access_token, plain_refresh = await _issue_tokens(session, user, settings)
    await session.commit()
    return AuthResult(user=user, access_token=access_token, refresh_token=plain_refresh)


async def refresh(session: AsyncSession, *, refresh_token: str, settings: Settings) -> str:
    """刷新:校验 refresh 哈希 + 未过期 + 未吊销 → 签发新 access(不轮换 refresh)。"""
    token = await refresh_token_repo.get_by_hash(session, hash_refresh_token(refresh_token))
    now = utcnow()
    if token is None or token.expires_at <= now or token.revoked_at is not None:
        raise Unauthenticated("Invalid refresh token")
    user = await user_repo.get_by_id(session, token.user_id)
    if user is None:
        raise Unauthenticated("Invalid refresh token")
    return _access_token(user, settings)


async def logout(session: AsyncSession, *, user_id: int, refresh_token: str) -> None:
    """登出:按归属用户取 refresh(他人令牌 → `NotFound` 不泄露存在性)并吊销,提交。"""
    token = await refresh_token_repo.get_for_user_by_hash(
        session, user_id=user_id, token_hash=hash_refresh_token(refresh_token)
    )
    await refresh_token_repo.revoke(session, token)
    await session.commit()
