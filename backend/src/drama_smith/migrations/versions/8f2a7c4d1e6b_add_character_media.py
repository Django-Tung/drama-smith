"""add character media

Revision ID: 8f2a7c4d1e6b
Revises: c4a1f9e20b7d
Create Date: 2026-07-09 20:30:00.000000

M3 角色形象图:新增 `media` 富媒体统一元数据表(多态归属 + user_id 横切 + selected 单选
生成列兜底,对齐 database.md §3.7),并为 `episode_characters` 加 `image_media_id` 逻辑指针
(无 FK,与 episodes.current_analysis_id 同构 D3)。本期只走 kind='image'/owner_type='character'
一条通路;shot/library/video/final 为 M3+ 预留枚举值。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# Alembic 版本标识。
revision: str = '8f2a7c4d1e6b'
down_revision: str | None = 'c4a1f9e20b7d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- 富媒体元数据表 ----
    op.create_table('media',
        sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('kind', sa.Enum('image', 'video', 'final'), nullable=False),
        # 多态归属:owner_type + owner_id(逻辑指针,不加 FK——多态 id 跨表无意义)。
        sa.Column('owner_type', sa.Enum('character', 'shot', 'library', 'episode'), nullable=False),
        sa.Column('owner_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('source', sa.Enum('upload', 'generate'), nullable=False),
        sa.Column('storage_provider', sa.String(length=32), server_default=sa.text("'local'"), nullable=False),
        sa.Column('storage_key', sa.String(length=512), nullable=False),
        sa.Column('content_type', sa.String(length=64), nullable=False),
        sa.Column('size_bytes', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('duration_sec', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('selected', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('status', sa.Enum('ready', 'processing', 'failed'), server_default=sa.text("'ready'"), nullable=False),
        sa.Column('extra', mysql.JSON(), nullable=True),
        # 生成列:selected 行产出归属键,UNIQUE 借 MySQL「多 NULL 并存」保证同 owner 恰一条 selected
        # (镜像 model_configs.active_key);应用层亦先翻旧 selected=false 再插新,此为竞态兜底。
        sa.Column('selected_key', sa.String(length=128), sa.Computed("CASE WHEN selected=1 THEN CONCAT(user_id,'-',owner_type,'-',owner_id) ELSE NULL END", persisted=False), nullable=True),
        sa.Column('provider_task', sa.String(length=256), nullable=True),
        sa.Column('last_tested_at', mysql.DATETIME(fsp=3), nullable=True),
        sa.Column('updated_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.Column('created_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_media_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_media')),
        sa.UniqueConstraint('selected_key', name=op.f('uq_media_selected_key')),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_0900_ai_ci'
    )
    # 复合索引覆盖多态归属查询;命名按 convention 取首列(D12 约定)。
    op.create_index(op.f('ix_media_user_id'), 'media', ['user_id', 'owner_type', 'owner_id'], unique=False)

    # ---- episode_characters.image_media_id(M3 形象图指针;逻辑指针,不加 FK)----
    op.add_column(
        'episode_characters',
        sa.Column('image_media_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=True),
    )


def downgrade() -> None:
    # 先删指针列(episode_characters 引用 media 但无 FK,删列无依赖);再删 media 表。
    # MySQL:drop_table 会级联删除表上的索引与外键,故直接删表即可(见 model_configs 迁移同款注释)。
    op.drop_column('episode_characters', 'image_media_id')
    op.drop_table('media')
