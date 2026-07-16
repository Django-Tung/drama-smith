"""接口层依赖:OAuth2 Bearer、Security 薄适配、当前用户。

设计依据(`design.md` D15 / D18、`backend.md` §4):
- `Security` 为薄适配:读 settings 后把 `secret` / `ttl` 显式传入 `core.security` 原语;
  验签失败(pyjwt 原生异常)在此映射为 `Unauthenticated`(401),原语保持纯粹。
- `get_current_user`:取 Bearer token → 验签 → 取用户 → 校验未锁定(锁定 → `Locked`)。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.config import get_mek, get_settings
from drama_smith.core.errors import Locked, Unauthenticated
from drama_smith.core.security import create_access_token, verify_access_token
from drama_smith.db.base import utcnow
from drama_smith.db.models import User
from drama_smith.db.repositories import user_repo
from drama_smith.db.session import get_session
from drama_smith.storage import FileStore
from drama_smith.tasks import TaskExecutor

# `tokenUrl` 仅用于 OpenAPI / Swagger「Authorize」表单展示;实际登录端点接收 JSON。
oauth_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


@dataclass(frozen=True)
class Security:
    """`core.security` 原语与 settings 之间的薄适配(便于阶段六单测注入)。"""

    secret: str
    access_ttl_seconds: int

    def issue_access_token(self, user_id: int, username: str) -> str:
        return create_access_token(user_id, username, self.secret, self.access_ttl_seconds)

    def verify_access_token(self, token: str) -> Mapping[str, Any]:
        try:
            return verify_access_token(token, self.secret)
        except jwt.PyJWTError as exc:
            # 过期 / 签名错误 / 格式错误等一律视为未认证(→ 401),不细分以收敛信息面。
            raise Unauthenticated("Invalid or expired access token") from exc


def get_security() -> Security:
    """FastAPI 依赖:按当前 settings 构造 `Security`(支持测试期 `override_settings`)。"""
    settings = get_settings()
    return Security(
        secret=settings.jwt_secret.get_secret_value(),
        access_ttl_seconds=settings.jwt_access_ttl_seconds,
    )


def get_crypto() -> bytes:
    """FastAPI 依赖:返回 MEK(base64 解码后的 32B,读 `DS_MEK`)。

    service 层据此解密/封存 API Key;支持测试期 `override_settings`。明文 MEK 不入 OpenAPI / 日志。
    """
    return get_mek()


def get_executor(request: Request) -> TaskExecutor:
    """FastAPI 依赖:从 `app.state.executor` 取进程内执行器(`main.lifespan` 构造注入)。

    analyze/optimize 等异步用例经此把 work 闭包提交执行器;`app.state.executor` 由 lifespan
    在启动期构造、`recover_running()` 恢复残留 running、关闭期 `shutdown()` 收口。测试触发
    lifespan(`async with lifespan(app)` 或 `with TestClient(app)`)即注入;未注入则 fail-fast。
    """
    executor: TaskExecutor | None = getattr(request.app.state, "executor", None)
    if executor is None:
        raise RuntimeError("TaskExecutor 未注入 app.state(检查 lifespan 是否已启动)")
    return executor


def get_file_store(request: Request) -> FileStore:
    """FastAPI 依赖:从 `app.state.file_store` 取进程内 FileStore(`main.lifespan` 构造注入)。

    形象图上传 / 生成 / 读取经此拿存储抽象(落盘 + 签名 URL);`app.state.file_store` 由 lifespan
    在启动期构造 + `ensure_root()`;未注入则 fail-fast(测试需 override `client` 注入替身)。
    """
    file_store: FileStore | None = getattr(request.app.state, "file_store", None)
    if file_store is None:
        raise RuntimeError("FileStore 未注入 app.state(检查 lifespan 是否已启动)")
    return file_store


async def get_current_user(
    token: Annotated[str, Depends(oauth_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
    sec: Annotated[Security, Depends(get_security)],
) -> User:
    """解析 Bearer token 并返回已认证、未锁定的用户。

    - 无 / 坏 / 过期令牌:OAuth2 scheme 抛 401,或 `verify_access_token` 抛 `Unauthenticated`。
    - 令牌主体已不存在(如用户被删):视为未认证,迫使重新登录(`Unauthenticated`)。
    - 账号被锁定:`Locked`(423)。
    """
    claims = sec.verify_access_token(token)
    user = await user_repo.get_by_id(session, int(claims["sub"]))
    if user is None:
        raise Unauthenticated("Authentication required")
    if user.locked_until is not None and user.locked_until > utcnow():
        raise Locked("Account is locked")
    return user


# ---- 路由复用的依赖别名(canonical home;各路由 `from drama_smith.api.deps import ...`)----
# `Annotated[T, Depends(...)]` 别名让端点签名简洁、一致;`ExecutorDep` 仅异步用例(analyze /
# optimize / cancel)需要。沿用 `api/models.py` 既有范式,集中在此避免跨路由复制。
SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]
MekDep = Annotated[bytes, Depends(get_crypto)]
ExecutorDep = Annotated[TaskExecutor, Depends(get_executor)]
FileStoreDep = Annotated[FileStore, Depends(get_file_store)]
