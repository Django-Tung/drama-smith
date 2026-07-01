"""`refresh_tokens` 表模型(对齐 `docs/tech-solution/database.md` §3.1)。

可吊销刷新令牌:仅存哈希不存明文(D4);按 `user_id` 归属,用户删除时级联清理。
仅有 `created_at`(令牌不可变,吊销靠 `revoked_at` 标记,无 `updated_at`)。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.orm import Mapped, mapped_column

from drama_smith.db.base import Base, CreatedAtMixin


class RefreshToken(CreatedAtMixin, Base):
    __tablename__ = "refresh_tokens"
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
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(MySQLDateTime(fsp=3), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(MySQLDateTime(fsp=3), nullable=True)
