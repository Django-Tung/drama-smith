"""任务 6.2:登录防爆破测试(账号维度;5 次锁定 / 15min 自动解锁 / 成功重置计数)。

对应 spec「Brute-Force Lockout」三场景。锁定时长不实等 15 分钟,改用直接置
`locked_until` 为过去时间来模拟窗口流逝(逻辑分支等价)。
"""

from __future__ import annotations

from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.db.base import utcnow
from drama_smith.db.models import User
from tests.helpers import RegisterUser, unique_username

_PASSWORD = "Sup3rSecret!"
_MAX_FAILURES = 5  # 与 Settings.login_max_failures 默认值一致


async def _fetch_user(session: AsyncSession, username: str) -> User:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one()


async def _wrong_login(client: AsyncClient, username: str) -> int:
    """发起一次错误密码登录,返回 HTTP 状态码。"""
    resp = await client.post(
        "/api/auth/login", json={"username": username, "password": "WrongPass1"}
    )
    return resp.status_code


class TestBruteForceLockout:
    async def test_account_locked_after_five_failures(
        self, client: AsyncClient, register_user: RegisterUser, db_session: AsyncSession
    ) -> None:
        username = unique_username()
        await register_user(username=username, password=_PASSWORD)

        # 连续 5 次失败:每次仍返回 401(第 5 次失败时才置 locked_until)。
        for _ in range(_MAX_FAILURES):
            assert await _wrong_login(client, username) == 401

        # 锁已写入:计数到 5、locked_until 指向未来。
        user = await _fetch_user(db_session, username)
        assert user.failed_login_count == _MAX_FAILURES
        assert user.locked_until is not None
        assert user.locked_until > utcnow()

        # 第 6 次:即使密码正确也返回 locked(423),不放过锁定期内的请求。
        resp = await client.post(
            "/api/auth/login", json={"username": username, "password": _PASSWORD}
        )
        assert resp.status_code == 423
        assert resp.json()["error"]["code"] == "locked"

    async def test_lock_auto_expires_and_resets_counter(
        self, client: AsyncClient, register_user: RegisterUser, db_session: AsyncSession
    ) -> None:
        username = unique_username()
        await register_user(username=username, password=_PASSWORD)
        for _ in range(_MAX_FAILURES):
            await _wrong_login(client, username)

        # 把锁定窗口「快进」到过去,模拟 15 分钟自然流逝。
        user = await _fetch_user(db_session, username)
        user.locked_until = utcnow() - timedelta(minutes=1)
        await db_session.commit()

        # 过期后用正确密码可登录,且计数被重置(spec「Lock auto-expires → counter reset」)。
        resp = await client.post(
            "/api/auth/login", json={"username": username, "password": _PASSWORD}
        )
        assert resp.status_code == 200

        await db_session.refresh(user)
        assert user.failed_login_count == 0
        assert user.locked_until is None

    async def test_successful_login_resets_counter(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        username = unique_username()
        await register_user(username=username, password=_PASSWORD)

        # 先累积 3 次失败(未到阈值),再用正确密码登录 → 计数清零。
        for _ in range(3):
            await _wrong_login(client, username)
        resp = await client.post(
            "/api/auth/login", json={"username": username, "password": _PASSWORD}
        )
        assert resp.status_code == 200

        # 重置后再失败 4 次仍未锁(计数从 0 起算,< 5),证明此前 3 次未结转。
        for _ in range(4):
            assert await _wrong_login(client, username) == 401
