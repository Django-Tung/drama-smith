"""应用配置(pydantic-settings)。

完整字段见 `docs/tech-solution/backend.md` §10;当前仅含骨架启动所需
(运行环境 + CORS),MySQL/JWT/MEK 等字段在后续任务组补全。
"""

import base64
import binascii
from collections.abc import Callable
from typing import Annotated, Any, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_LiteralEnv = Literal["dev", "test", "prod"]

# 开发期兜底值:生产环境必须经环境变量覆盖(见 Settings._enforce_prod_secrets)。
_INSECURE_JWT_FALLBACK = "dev-insecure-change-me-in-production"
_DEV_DATABASE_URL = "mysql+asyncmy://drama:drama@127.0.0.1:3306/drama_smith?charset=utf8mb4"

# MEK(master encryption key)长度:`DS_MEK` 经 base64 解码后须恰为 32 字节(AES-256)。
_MEK_LEN_BYTES = 32


class Settings(BaseSettings):
    """从环境变量 / `.env` 读取的应用配置。"""

    model_config = SettingsConfigDict(
        env_prefix="ds_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 运行环境 ----
    app_name: str = "drama-smith"
    environment: _LiteralEnv = "dev"

    # ---- 数据库(外部 MySQL;asyncmy 驱动 + utf8mb4)----
    database_url: str = _DEV_DATABASE_URL

    # ---- 鉴权 / 令牌 ----
    # 开发默认值仅用于本地;生产必须提供安全值(_enforce_prod_secrets 会拦截)。
    jwt_secret: SecretStr = SecretStr(_INSECURE_JWT_FALLBACK)  # noqa: S105
    jwt_access_ttl_seconds: int = 900  # 访问令牌有效期(15 分钟)
    refresh_ttl_days: int = 7

    # ---- BYOK 主密钥(MEK)----
    # 信封加密根密钥:经环境变量 `DS_MEK`(base64 32B)注入,不入库/日志/OpenAPI。
    # 字段名用 `mek`:`env_prefix="ds_"` 自动拼出 env `DS_MEK`(与 jwt_secret/database_url 同范式)。
    # 无安全默认值 → 必填;长度校验在 `get_mek()`(缺失/非 32B 启动即拒,design D2)。
    mek: SecretStr

    # ---- 登录防爆破(仅按账号维度)----
    login_max_failures: int = 5
    login_lock_minutes: int = 15

    # ---- CORS:逗号分隔的允许来源(开发期默认放行 Vite 源)----
    # NoDecode:禁用 pydantic-settings 对 list 的 JSON 解码,改为交由下面的 before 校验器按 CSV 拆分。
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"],
    )

    # ---- 任务执行器并发上限(M2;进程内 asyncio 执行器)----
    # 每用户并发任务数(超限自然排队 `pending`)、全局协程上限;均经 `DS_` env 可覆盖。
    # 取值权衡 BYOK 成本:并发越高吞吐越大,但供应商并发/费用同步上升(见 总纲 §6)。
    max_tasks_per_user: int = 4
    max_global_workers: int = 8

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: Any) -> Any:
        """允许环境变量以逗号分隔字符串给出。"""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _enforce_prod_secrets(self) -> Self:
        """生产环境禁止沿用开发默认密钥。"""
        if (
            self.environment == "prod"
            and self.jwt_secret.get_secret_value() == _INSECURE_JWT_FALLBACK
        ):
            msg = "DS_JWT_SECRET 必须在生产环境设置为安全随机值"
            raise ValueError(msg)
        return self


_settings_factory: Callable[[], Settings] | None = None


def get_settings() -> Settings:
    """返回当前 Settings 实例(便于测试替换,见 `override_settings`)。"""
    if _settings_factory is None:
        return Settings()
    return _settings_factory()


def override_settings(factory: Callable[[], Settings] | None) -> None:
    """注入/清除 Settings 工厂(测试用)。"""
    global _settings_factory  # noqa: PLW0603
    _settings_factory = factory


def get_mek() -> bytes:
    """返回 MEK 原始字节(base64 解码 `ds_mek` 并校验 32B)。

    design D2:缺失或非 32B → 抛 `ValueError`(启动期 fail-fast,避免静默落弱密钥)。
    MEK 仅驻内存;调用方(信封加解密、`get_crypto`)不得持久化或落日志。
    """
    raw = get_settings().mek.get_secret_value()
    try:
        mek = base64.b64decode(raw, validate=True)
    except binascii.Error as exc:
        msg = "DS_MEK 必须是 base64 编码(用 `openssl rand -base64 32` 生成)"
        raise ValueError(msg) from exc
    if len(mek) != _MEK_LEN_BYTES:
        msg = f"DS_MEK 解码后须为 {_MEK_LEN_BYTES} 字节,实际 {len(mek)} 字节"
        raise ValueError(msg)
    return mek
