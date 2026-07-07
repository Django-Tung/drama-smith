"""`shot_characters` 表模型(对齐 `docs/tech-solution/database.md` §3.6)。

单镜出场角色(多对多);复合主键 `(shot_id, episode_character_id)`,无独立时间戳。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column

from drama_smith.db.base import Base


class ShotCharacter(Base):
    """分镜-角色关联:某镜出场角色及该镜内作用。"""

    __tablename__ = "shot_characters"
    __table_args__ = ({"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"},)

    shot_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        ForeignKey("shots.id", ondelete="CASCADE"),
        primary_key=True,
    )
    episode_character_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(BIGINT(unsigned=True), "mysql"),
        ForeignKey("episode_characters.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_in_shot: Mapped[str | None] = mapped_column(String(32), nullable=True)
