"""`model_configs` 表模型(BYOK;对齐 `docs/tech-solution/database.md` §3.2,design D1 A2+m2)。

每用户每用途(text/image/video)可有多条模型凭证;经**生成列 `active_key` + UNIQUE**
保证「恰一条 active」(design D3)。API Key 经信封加密落 `api_key_ciphertext` /
`dek_ciphertext` 两个自包含 blob(`nonce ‖ ct ‖ tag`,无单独 `api_key_iv` 列,A2);
脱敏串 `api_key_masked` 写时落库(m2),读路径不碰 MEK。
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
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT, JSON, VARBINARY
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.orm import Mapped, mapped_column

from drama_smith.db.base import Base, TimestampMixin

# 生成列表达式:仅 active 行产出 `(user_id)-(purpose)`,非 active 行为 NULL。
# UNIQUE 索引借 MySQL「允许多行 NULL」语义,保证每 (user_id,purpose) 恰一条 active(design D3)。
_ACTIVE_KEY_EXPR = "CASE WHEN is_active=1 THEN CONCAT(user_id,'-',purpose) ELSE NULL END"


class ModelConfig(TimestampMixin, Base):
    """用户自配的模型凭证(BYOK);三类用途各自 0..N 条、恰一条 active。"""

    __tablename__ = "model_configs"
    __table_args__ = (
        # 命名约定 → uq_model_configs_active_key;挂虚拟生成列上,MySQL 允许 UNIQUE on VIRTUAL。
        UniqueConstraint("active_key"),
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
        index=True,
    )
    purpose: Mapped[str] = mapped_column(
        Enum("text", "image", "video", native_enum=True),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # A2:两层自包含 blob(nonce ‖ ct ‖ tag);删除了原 schema 的 `api_key_iv` 列。
    api_key_ciphertext: Mapped[bytes] = mapped_column(VARBINARY(512), nullable=False)
    dek_ciphertext: Mapped[bytes] = mapped_column(VARBINARY(512), nullable=False)
    # m2:脱敏串写时落库,列表/详情直出,读路径不碰 MEK、不解密。
    api_key_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provider_options: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(
        Enum("active", "invalid", native_enum=True),
        nullable=False,
        server_default=text("'active'"),
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(MySQLDateTime(fsp=3), nullable=True)
    # 虚拟生成列(只读,由 MySQL 计算);active 行才产出键值,UNIQUE 索引挂其上。
    active_key: Mapped[str | None] = mapped_column(
        String(128),
        Computed(_ACTIVE_KEY_EXPR, persisted=False),
        nullable=True,
    )
