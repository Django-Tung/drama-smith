"""任务 6.1:认证主链路集成测试(register / login / logout / refresh / me)。

覆盖 spec「User Authentication」各场景的正常与异常路径。每条用例在独立(已 TRUNCATE)
的测试库上运行,无跨用例状态泄漏。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.db.base import utcnow
from drama_smith.db.models import RefreshToken, User
from tests.helpers import RegisterUser, unique_username

_PASSWORD = "Sup3rSecret!"
_WEAK_PASSWORDS = [
    "short1",  # 长度 < 8
    "allletters",  # 无数字
    "12345678",  # 无字母
]
_BAD_USERNAMES = [
    "ab",  # 长度 < 3
    "a" * 33,  # 长度 > 32
    "bad name!",  # 非法字符
]


async def _fetch_user(session: AsyncSession, username: str) -> User:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one()


class TestRegister:
    """`POST /api/auth/register`。"""

    async def test_creates_user_and_issues_tokens(
        self, client: AsyncClient, register_user: RegisterUser, db_session: AsyncSession
    ) -> None:
        username = unique_username()
        data = await register_user(username=username, password=_PASSWORD)

        # 信封内令牌齐全;token_type 固定 Bearer。
        assert data["token_type"] == "Bearer"
        assert data["access_token"]
        assert data["refresh_token"]

        # 密码以 argon2id 哈希落库;明文绝不入库(spec「Password Hashing」)。
        user = await _fetch_user(db_session, username)
        assert user.password_hash.startswith("$argon2id$")
        assert _PASSWORD not in user.password_hash
        assert user.failed_login_count == 0
        assert user.locked_until is None

    async def test_duplicate_username_is_conflict(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        username = unique_username()
        await register_user(username=username)

        resp = await client.post(
            "/api/auth/register", json={"username": username, "password": _PASSWORD}
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "conflict"

    @pytest.mark.parametrize("username", _BAD_USERNAMES)
    async def test_invalid_username_is_validation_error(
        self, client: AsyncClient, username: str
    ) -> None:
        resp = await client.post(
            "/api/auth/register", json={"username": username, "password": _PASSWORD}
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"

    @pytest.mark.parametrize("password", _WEAK_PASSWORDS)
    async def test_weak_password_is_validation_error(
        self, client: AsyncClient, password: str
    ) -> None:
        resp = await client.post(
            "/api/auth/register", json={"username": unique_username(), "password": password}
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"

    async def test_validation_failure_creates_no_user(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        resp = await client.post(
            "/api/auth/register",
            json={"username": "bad name!", "password": _PASSWORD},
        )
        assert resp.status_code == 422
        users = (await db_session.execute(select(User))).scalars().all()
        assert users == []


class TestLogin:
    """`POST /api/auth/login`。"""

    async def test_success_issues_tokens_and_records_login(
        self, client: AsyncClient, register_user: RegisterUser, db_session: AsyncSession
    ) -> None:
        username = unique_username()
        await register_user(username=username, password=_PASSWORD)

        resp = await client.post(
            "/api/auth/login", json={"username": username, "password": _PASSWORD}
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["token_type"] == "Bearer"

        # 成功登录重置计数并记录 last_login_at(spec「Successful login resets counter」)。
        user = await _fetch_user(db_session, username)
        assert user.failed_login_count == 0
        assert user.last_login_at is not None

    async def test_wrong_password_unauthenticated_and_increments(
        self, client: AsyncClient, register_user: RegisterUser, db_session: AsyncSession
    ) -> None:
        username = unique_username()
        await register_user(username=username, password=_PASSWORD)

        resp = await client.post(
            "/api/auth/login", json={"username": username, "password": "WrongPass1"}
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthenticated"

        user = await _fetch_user(db_session, username)
        assert user.failed_login_count == 1

    async def test_unknown_user_is_unauthenticated(self, client: AsyncClient) -> None:
        # 不存在的账号同样返回 401,不泄露账号是否存在。
        resp = await client.post(
            "/api/auth/login",
            json={"username": unique_username("ghost"), "password": _PASSWORD},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthenticated"


class TestRefresh:
    """`POST /api/auth/refresh`。"""

    async def test_valid_refresh_issues_new_access(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        data = await register_user(password=_PASSWORD)
        resp = await client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})
        assert resp.status_code == 200
        refreshed = resp.json()["data"]
        assert refreshed["token_type"] == "Bearer"
        # 新 access 可用:能通过 /me 鉴权(行为校验,不依赖令牌字符串差异)。
        me_resp = await client.get(
            "/api/me", headers={"Authorization": f"Bearer {refreshed['access_token']}"}
        )
        assert me_resp.status_code == 200
        # 不轮换 refresh:响应不含新 refresh_token(spec「no rotation」)。
        assert "refresh_token" not in refreshed

    async def test_revoked_refresh_is_rejected(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        data = await register_user(password=_PASSWORD)
        # 登出吊销该 refresh。
        logout_resp = await client.post(
            "/api/auth/logout",
            json={"refresh_token": data["refresh_token"]},
            headers={"Authorization": f"Bearer {data['access_token']}"},
        )
        assert logout_resp.status_code == 204

        resp = await client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthenticated"

    async def test_expired_refresh_is_rejected(
        self, client: AsyncClient, register_user: RegisterUser, db_session: AsyncSession
    ) -> None:
        data = await register_user(password=_PASSWORD)
        # 直接把令牌过期时间置为过去,模拟自然过期。
        token = (await db_session.execute(select(RefreshToken))).scalar_one()
        token.expires_at = utcnow() - timedelta(minutes=1)
        await db_session.commit()

        resp = await client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthenticated"


class TestMeAndLogout:
    """`GET /api/me` 与 `POST /api/auth/logout`。"""

    async def test_me_returns_current_user(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        username = unique_username()
        data = await register_user(username=username, password=_PASSWORD)

        resp = await client.get(
            "/api/me", headers={"Authorization": f"Bearer {data['access_token']}"}
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["username"] == username
        assert isinstance(body["id"], int)
        # 本里程碑文本模型尚未接入,恒为 false。
        assert body["text_model_configured"] is False

    async def test_logout_revokes_refresh(
        self, client: AsyncClient, register_user: RegisterUser, db_session: AsyncSession
    ) -> None:
        data = await register_user(password=_PASSWORD)

        resp = await client.post(
            "/api/auth/logout",
            json={"refresh_token": data["refresh_token"]},
            headers={"Authorization": f"Bearer {data['access_token']}"},
        )
        assert resp.status_code == 204

        token = (await db_session.execute(select(RefreshToken))).scalar_one()
        assert token.revoked_at is not None
