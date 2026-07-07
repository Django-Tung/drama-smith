"""`tasks` 表模型(对齐 `docs/tech-solution/database.md` §3.8)。

任务中心:持久化、可恢复([FR-A11](../requirements/features/analysis.md))。横切表仍带 `user_id`
(隔离主力),`episode_id` 可空(跨剧集汇总)。时间线
`created_at/started_at/finished_at`(无 `updated_at`)。
索引 `(user_id, status, created_at)` 支撑任务页过滤、`episode_id` 支撑跳转。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, String, text
from sqlalchemy.dialects.mysql import BIGINT, JSON, TINYINT
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.orm import Mapped, mapped_column

from drama_smith.db.base import Base, CreatedAtMixin


class Task(CreatedAtMixin, Base):
    """任务:进程内 asyncio 执行器调度,持久化进度/状态/错误供恢复。"""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_user_status_created", "user_id", "status", "created_at"),
        Index("ix_tasks_episode_id", "episode_id"),
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
    episode_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=True,
    )
    type: Mapped[str] = mapped_column(
        Enum("optimize", "analyze", "image", "video", "render", native_enum=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "pending",
            "running",
            "succeeded",
            "failed",
            "canceled",
            "interrupted",
            native_enum=True,
        ),
        nullable=False,
    )
    progress: Mapped[int] = mapped_column(
        TINYINT(unsigned=True),
        nullable=False,
        server_default=text("0"),
    )
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trigger: Mapped[str] = mapped_column(
        Enum("single", "batch", native_enum=True),
        nullable=False,
        server_default=text("'single'"),
    )
    input_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_refs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 时间线:created_at 由 CreatedAtMixin 提供(NOT NULL);started/finished 可空。
    started_at: Mapped[datetime | None] = mapped_column(MySQLDateTime(fsp=3), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(MySQLDateTime(fsp=3), nullable=True)
