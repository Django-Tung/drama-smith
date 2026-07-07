"""`episodes` 表模型(对齐 `docs/tech-solution/database.md` §3.4 + design D11)。

剧集 = 流水线容器;归属经 `drama_id → dramas.user_id` 链(D1)。整集画幅/风格统一。
`current_analysis_id` 为当前生效分析指针(D11):**逻辑指针、不加物理 FK**,
以避免与 `analyses.episode_id` 循环外键;归属/越权由应用层(`analysis_repo`)把关。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Enum, ForeignKey, String, text
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.orm import Mapped, mapped_column

from drama_smith.db.base import Base, TimestampMixin


class Episode(TimestampMixin, Base):
    """剧集:流水线容器,经 drama 归属用户。"""

    __tablename__ = "episodes"
    __table_args__ = ({"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"},)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        primary_key=True,
        autoincrement=True,
    )
    drama_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        ForeignKey("dramas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    aspect_ratio: Mapped[str] = mapped_column(
        Enum("16:9", "9:16", "1:1", "4:3", native_enum=True),
        nullable=False,
    )
    style_preset: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("draft", "analyzing", "ready", "rendering", "done", native_enum=True),
        nullable=False,
        server_default=text("'draft'"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(MySQLDateTime(fsp=3), nullable=True)
    # D11:当前生效分析指针。逻辑指针(**不加物理 FK**),避免与 analyses.episode_id 循环外键;
    # 指向 analyses.id(NULL 表示尚未拆解)。归属校验在 analysis_repo 应用层把关。
    current_analysis_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        nullable=True,
    )
