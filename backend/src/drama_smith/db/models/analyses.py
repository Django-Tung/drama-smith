"""`analyses` 表模型(对齐 `docs/tech-solution/database.md` §3.6 + design D11)。

一次拆解的完整结果与配置快照;`result` 为角色/情节线/冲突/节奏四维整体读的 JSON(§7)。
D11 追加 `script_version_id`:**物理 FK→script_versions**,记录发起拆解时所基于的剧本版本
(= 当时 `scripts.current_version_id`),使优化/比对可溯源到具体版本。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Enum, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import Mapped, mapped_column

from drama_smith.db.base import Base, TimestampMixin


class Analysis(TimestampMixin, Base):
    """分析产物:四维结果 + 配置快照,append-only(D11 版本化)。"""

    __tablename__ = "analyses"
    __table_args__ = ({"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"},)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        primary_key=True,
        autoincrement=True,
    )
    episode_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "succeeded", "failed", native_enum=True),
        nullable=False,
    )
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    config_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # D11:发起拆解时的剧本版本(物理 FK);随 script_version 硬删级联
    # (本表亦属 episode,常规路径随 episode 级联删)。
    script_version_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        ForeignKey("script_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
