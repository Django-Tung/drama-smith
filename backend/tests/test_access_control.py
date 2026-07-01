"""任务 6.3:鉴权与多租户隔离测试。

- 访问令牌:`无 / 坏 / 过期` 一律 401(spec「Access Token Authentication」)。
- 多租户:越权访问他人资源 → 404,不泄露存在性(spec「Multi-Tenant Data Isolation」)。
  本里程碑以「按 `user_id` 归属的刷新令牌」为载体,在 logout 端点与仓储层各验证一次。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.config import get_settings
from drama_smith.core.errors import NotFound
from drama_smith.core.security import create_access_token
from drama_smith.db.models import RefreshToken, User
from drama_smith.db.repositories import refresh_token_repo
from tests.helpers import RegisterUser, unique_username

_PASSWORD = "Sup3rSecret!"


class TestAccessTokenAuth:
    """`Authorization: Bearer <access_token>` 守卫。"""

    async def test_missing_token_is_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/me")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthenticated"

    async def test_malformed_token_is_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/me", headers={"Authorization": "Bearer not.a.valid.token"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthenticated"

    async def test_expired_token_is_unauthenticated(self, client: AsyncClient) -> None:
        # 手工签发一张已过期令牌(ttl 为负);验签先于用户查找失败,故 sub 无关紧要。
        secret = get_settings().jwt_secret.get_secret_value()
        expired = create_access_token(999_999, "nobody", secret, ttl_seconds=-10)
        resp = await client.get("/api/me", headers={"Authorization": f"Bearer {expired}"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthenticated"

    async def test_valid_token_authorizes(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        username = unique_username()
        data = await register_user(username=username, password=_PASSWORD)
        resp = await client.get(
            "/api/me", headers={"Authorization": f"Bearer {data['access_token']}"}
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["username"] == username


class TestMultiTenantIsolation:
    """刷新令牌按 `user_id` 归属隔离(D6 范式)。"""

    async def test_logout_other_users_refresh_is_not_found(
        self, client: AsyncClient, register_user: RegisterUser
    ) -> None:
        # A、B 各注册;A 持自己的 access,却尝试吊销 B 的 refresh。
        alice = await register_user(username=unique_username("alice"), password=_PASSWORD)
        bob = await register_user(username=unique_username("bob"), password=_PASSWORD)

        resp = await client.post(
            "/api/auth/logout",
            json={"refresh_token": bob["refresh_token"]},
            headers={"Authorization": f"Bearer {alice['access_token']}"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "not_found"

        # B 的 refresh 未被吊销,仍可正常刷新 —— A 的越权操作无效。
        refresh_resp = await client.post(
            "/api/auth/refresh", json={"refresh_token": bob["refresh_token"]}
        )
        assert refresh_resp.status_code == 200

    async def test_repo_scoping_hides_other_users_token(
        self, client: AsyncClient, register_user: RegisterUser, db_session: AsyncSession
    ) -> None:
        alice_name = unique_username("alice")
        bob_name = unique_username("bob")
        await register_user(username=alice_name, password=_PASSWORD)
        await register_user(username=bob_name, password=_PASSWORD)

        alice_row = (
            await db_session.execute(select(User).where(User.username == alice_name))
        ).scalar_one()
        bob_row = (
            await db_session.execute(select(User).where(User.username == bob_name))
        ).scalar_one()
        alice_token = (
            await db_session.execute(
                select(RefreshToken).where(RefreshToken.user_id == alice_row.id)
            )
        ).scalar_one()

        # 归属正确 → 取得到;查 A 的哈希却带 B 的 id → NotFound(不泄露存在性)。
        found = await refresh_token_repo.get_for_user_by_hash(
            db_session, user_id=alice_row.id, token_hash=alice_token.token_hash
        )
        assert found.id == alice_token.id
        with pytest.raises(NotFound):
            await refresh_token_repo.get_for_user_by_hash(
                db_session, user_id=bob_row.id, token_hash=alice_token.token_hash
            )
