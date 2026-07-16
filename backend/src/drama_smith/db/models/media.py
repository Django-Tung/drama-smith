"""`media` 表模型(富媒体统一元数据,对齐 `docs/tech-solution/database.md` §3.7,M3)。

多态归属:`owner_type ∈ {character, shot, library, episode}` + `owner_id`(BIGINT,逻辑指针,
不加 FK——多态 id 跨表无意义);横切带 `user_id`(归属校验,与所有业务表一致)。
`kind ∈ {image, video, final}`;`source ∈ {upload, generate}`;`storage_provider` 默认 `'local'`
(`storage_key` 为 `FileStore` 相对路径)。本期只落 `kind='image'` + `owner_type='character'` 一条通路
(角色形象图);`shot`/`library`/`video`/`final` 为 M3+ 预留枚举值。

「同 owner 恰一条 selected」由生成列 `selected_key` + UNIQUE 兜底(镜像 `model_configs.active_key`):
selected 行产出 `user_id-owner_type-owner_id`,非 selected 行为 NULL,MySQL UNIQUE 允许多 NULL 并存,
故旧形象图可保留 `selected=false`(D9)。应用层 `media_repo.create` 仍先翻旧 selected=false 再插新,
DB 约束为竞态兜底。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.orm import Mapped, mapped_column

from drama_smith.db.base import Base, TimestampMixin

# 生成列:selected 行产出归属键,UNIQUE 借 MySQL「多 NULL 并存」保证同 owner 恰一条 selected。
_SELECTED_KEY_EXPR = (
    "CASE WHEN selected=1 THEN CONCAT(user_id,'-',owner_type,'-',owner_id) ELSE NULL END"
)


class Media(TimestampMixin, Base):
    """富媒体统一元数据行(图片 / 视频 / 成片);字节落 `FileStore`,本表只存元数据 + 归属。"""

    __tablename__ = "media"
    __table_args__ = (
        UniqueConstraint("selected_key"),
        # 复合索引覆盖多态归属查询(按 owner 列形象图);命名按 convention 取首列(D12 约定)。
        Index("ix_media_user_id", "user_id", "owner_type", "owner_id"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        Enum("image", "video", "final", native_enum=True),
        nullable=False,
    )
    owner_type: Mapped[str] = mapped_column(
        Enum("character", "shot", "library", "episode", native_enum=True),
        nullable=False,
    )
    # 多态归属 id(逻辑指针,不加 FK);语义随 owner_type(角色 id / 分镜 id / …)。
    owner_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        Enum("upload", "generate", native_enum=True),
        nullable=False,
    )
    storage_provider: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'local'")
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        nullable=False,
    )
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(
        Numeric(precision=8, scale=2), nullable=True
    )
    selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(
        Enum("ready", "processing", "failed", native_enum=True),
        nullable=False,
        server_default=text("'ready'"),
    )
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # 虚拟生成列(只读,由 MySQL 计算);selected 行才产出键值,UNIQUE 索引挂其上。
    selected_key: Mapped[str | None] = mapped_column(
        String(128),
        Computed(_SELECTED_KEY_EXPR, persisted=False),
        nullable=True,
    )
    # 用于 generate 来源记录远程供应商任务 id 等(M3+ 视频轮询);本期 image 可空。
    provider_task: Mapped[str | None] = mapped_column(String(256), nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(MySQLDateTime(fsp=3), nullable=True)
