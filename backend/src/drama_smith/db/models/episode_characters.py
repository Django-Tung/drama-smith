"""`episode_characters` 表模型(对齐 `docs/tech-solution/database.md` §3.5)。

剧集内富字段角色(预置 / 拆解产出 / 库引入)。**M2 裁剪**:`source` 仅 `preset|analysis`
(无 `library`,留待 M4 角色库;无 `image_media_id`,留待 M3 形象图)。
归属经 `episode_id → dramas.user_id` 链(D1),不在本表冗余 `user_id`。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, String, text
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import Mapped, mapped_column

from drama_smith.db.base import Base, TimestampMixin


class EpisodeCharacter(TimestampMixin, Base):
    """剧集角色:富字段人设,供分镜出场引用与一致性生成。"""

    __tablename__ = "episode_characters"
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
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    role_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    persona: Mapped[str | None] = mapped_column(String(512), nullable=True)
    motivation: Mapped[str | None] = mapped_column(String(512), nullable=True)
    traits: Mapped[list | None] = mapped_column(JSON, nullable=True)
    appearance_desc: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # M2:`source` 仅 preset|analysis(library 留 M4;image_media_id 留 M3)。
    source: Mapped[str] = mapped_column(
        Enum("preset", "analysis", native_enum=True),
        nullable=False,
        server_default=text("'preset'"),
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
