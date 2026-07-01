"""`users` 表模型(对齐 `docs/tech-solution/database.md` §3.1)。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, String, text
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.orm import Mapped, mapped_column

from drama_smith.db.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    """用户账号;`failed_login_count`/`locked_until` 支撑按账号维度的防爆破(D5)。"""

    __tablename__ = "users"
    __table_args__ = ({"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"},)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        primary_key=True,
        autoincrement=True,
    )
    username: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    failed_login_count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(MySQLDateTime(fsp=3), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(MySQLDateTime(fsp=3), nullable=True)
