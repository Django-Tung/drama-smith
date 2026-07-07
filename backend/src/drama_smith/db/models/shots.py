"""`shots` 表模型(对齐 `docs/tech-solution/database.md` §3.6)。

分镜清单:逐镜独立行,可编辑/拆/合/排序([FR-A6](../requirements/features/analysis.md))。
`analysis_id` 指来源分析,`episode_id` 为冗余归属(列表/校验);`seq` 在 episode 内排序,
`(episode_id, seq)` 索引支撑分镜列表与事务内 dense-rank 重排(设计 D5)。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column

from drama_smith.db.base import Base, TimestampMixin


class Shot(TimestampMixin, Base):
    """分镜:逐镜行,可拆/合/排序,带可追溯字段。"""

    __tablename__ = "shots"
    __table_args__ = (
        Index("ix_shots_episode_id_seq", "episode_id", "seq"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        primary_key=True,
        autoincrement=True,
    )
    analysis_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    episode_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False)
    shot_type: Mapped[str | None] = mapped_column(
        Enum("wide", "medium", "close", "extreme_close", native_enum=True),
        nullable=True,
    )
    scene: Mapped[str | None] = mapped_column(String(128), nullable=True)
    plot_point: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dialogue: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_duration: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    camera_move: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_plotline: Mapped[str | None] = mapped_column(String(128), nullable=True)
    related_conflict: Mapped[str | None] = mapped_column(String(128), nullable=True)
