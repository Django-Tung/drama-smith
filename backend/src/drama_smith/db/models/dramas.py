"""`dramas` 表模型(对齐 `docs/tech-solution/database.md` §3.4)。

剧(Drama)为顶层容器,直接归属用户;软删(`deleted_at`),列表/详情带 `deleted_at IS NULL`。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, String, text
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.orm import Mapped, mapped_column

from drama_smith.db.base import Base, TimestampMixin


class Drama(TimestampMixin, Base):
    """剧:顶层容器,直接归属用户。"""

    __tablename__ = "dramas"
    __table_args__ = ({"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"},)

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
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    deleted_at: Mapped[datetime | None] = mapped_column(MySQLDateTime(fsp=3), nullable=True)
