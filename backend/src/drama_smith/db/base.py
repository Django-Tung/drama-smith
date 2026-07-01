"""SQLAlchemy 声明基类、命名约定、时间戳混入与异步引擎/会话工厂。

设计依据(`design.md`):
- **D11**:引擎/会话走懒工厂(模块级缓存 + `dispose_engine`),对齐 `core/config`
  的 `get_settings`/`override_settings` 模式 —— 阶段六集成测试可经 `override_settings`
  切临时库后 `await dispose_engine()` 丢弃旧引擎,无需 monkeypatch 模块全局。
- **D12**:`naming_convention`(约束/索引名稳定可复现)、`DATETIME(3)` naive-UTC、
  `updated_at` 走 MySQL `ON UPDATE CURRENT_TIMESTAMP`(裸 SQL 更新也能刷新,如
  `tasks` 启动恢复的 `UPDATE ... WHERE status='running'`,见 backend.md §7.4)。
  表/列的 utf8mb4 在各模型的 `__table_args__` 显式声明。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import MetaData, text
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from drama_smith.core.config import get_settings

# autogenerate 产出稳定、可读、可复现的约束/索引名(D12④)。
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """所有 ORM 模型的声明基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class CreatedAtMixin:
    """`created_at` 列:毫秒精度、插入时取库时间(`CURRENT_TIMESTAMP(3)`)。"""

    created_at: Mapped[datetime] = mapped_column(
        MySQLDateTime(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )


class TimestampMixin(CreatedAtMixin):
    """`created_at` + `updated_at`;后者由 MySQL 在任意 UPDATE 时刷新。"""

    updated_at: Mapped[datetime] = mapped_column(
        MySQLDateTime(fsp=3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
    )


def utcnow() -> datetime:
    """当前 UTC 时间(naive)。

    D12 约定时间戳 `DATETIME(3)` 存 naive-UTC;故业务写入与比对一律用本函数返回的
    naive 值,避免 aware(如 `datetime.now(UTC)`)与库读回的 naive 值比较报错。
    """
    return datetime.now(UTC).replace(tzinfo=None)


# ---- 异步引擎 / 会话工厂(懒加载,模块级缓存)----
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """返回缓存的异步引擎;首次调用时按 `Settings.database_url` 构建。

    `pool_pre_ping` 在借出连接前探活,规避 MySQL `wait_timeout` 断连;
    `pool_recycle` 主动回收,双保险。
    """
    global _engine
    if _engine is not None:
        return _engine
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    _engine = engine
    return engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """返回缓存的 `async_sessionmaker`。

    `expire_on_commit=False`:async 会话提交后访问属性会触发同步 IO 报错,
    关闭过期以允许提交后读取。
    """
    global _session_factory
    if _session_factory is not None:
        return _session_factory
    factory = async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)
    _session_factory = factory
    return factory


async def dispose_engine() -> None:
    """释放并清除缓存的引擎与会话工厂。

    `lifespan` 关停时调用;测试 `override_settings` 切库后调用以丢弃旧引擎。
    """
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
