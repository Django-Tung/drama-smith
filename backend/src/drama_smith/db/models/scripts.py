"""`scripts` 表模型(对齐 `docs/tech-solution/database.md` §3.4)。

每剧集 1:1 剧本容器(`episode_id` UNIQUE);`current_version_id` 指向当前生效版本。
与 `script_versions.script_id` 构成循环引用,故 `current_version_id` 为**逻辑指针、不加物理 FK**
(同 D11 的 `episodes.current_analysis_id` 心智模型),由 `script_repo` 应用层把关。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column

from drama_smith.db.base import Base, TimestampMixin


class Script(TimestampMixin, Base):
    """剧本容器:与剧集 1:1,持当前版本指针。"""

    __tablename__ = "scripts"
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
        unique=True,
    )
    # 逻辑指针(**不加物理 FK**):避免与 script_versions.script_id 循环;由 script_repo 把关。
    current_version_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        nullable=True,
    )
