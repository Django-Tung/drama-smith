"""`script_versions` 表模型(对齐 `docs/tech-solution/database.md` §3.4)。

不可变追加(`source` ∈ input/optimize);`content` 用 `MEDIUMTEXT`(剧本可能较长)。
仅有 `created_at`(版本不可变,无 `updated_at`)。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, text
from sqlalchemy.dialects.mysql import BIGINT, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from drama_smith.db.base import Base, CreatedAtMixin


class ScriptVersion(CreatedAtMixin, Base):
    """剧本版本:不可变追加,记录输入/优化产出的某版正文。"""

    __tablename__ = "script_versions"
    __table_args__ = ({"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"},)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        primary_key=True,
        autoincrement=True,
    )
    script_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        ForeignKey("scripts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    format: Mapped[str] = mapped_column(
        Enum("plain", "markdown", "fountain", native_enum=True),
        nullable=False,
        server_default=text("'markdown'"),
    )
    source: Mapped[str] = mapped_column(
        Enum("input", "optimize", native_enum=True),
        nullable=False,
    )
