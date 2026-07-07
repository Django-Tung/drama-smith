"""add analysis core

Revision ID: c4a1f9e20b7d
Revises: 04569358397f
Create Date: 2026-07-06 22:00:00.000000

剧目域(dramas/episodes/scripts/script_versions)、剧集角色(episode_characters)、
分析产物域(analyses/shots/shot_characters)、任务域(tasks)9 张表。
M2 裁剪:episode_characters.source 仅 preset|analysis(无 library);无 image_media_id。
D11:episodes.current_analysis_id 逻辑指针(不加 FK);analyses.script_version_id 物理 FK。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# Alembic 版本标识。
revision: str = 'c4a1f9e20b7d'
down_revision: str | None = '04569358397f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- 剧目域 ----
    op.create_table('dramas',
        sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('deleted_at', mysql.DATETIME(fsp=3), nullable=True),
        sa.Column('updated_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.Column('created_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_dramas_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_dramas')),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_0900_ai_ci'
    )
    op.create_index(op.f('ix_dramas_user_id'), 'dramas', ['user_id'], unique=False)

    op.create_table('episodes',
        sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), autoincrement=True, nullable=False),
        sa.Column('drama_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('title', sa.String(length=128), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('aspect_ratio', sa.Enum('16:9', '9:16', '1:1', '4:3'), nullable=False),
        sa.Column('style_preset', sa.String(length=64), nullable=True),
        sa.Column('status', sa.Enum('draft', 'analyzing', 'ready', 'rendering', 'done'), server_default=sa.text("'draft'"), nullable=False),
        sa.Column('deleted_at', mysql.DATETIME(fsp=3), nullable=True),
        # D11:当前生效分析指针(逻辑指针,不加 FK,避免与 analyses.episode_id 循环外键)。
        sa.Column('current_analysis_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=True),
        sa.Column('updated_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.Column('created_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.ForeignKeyConstraint(['drama_id'], ['dramas.id'], name=op.f('fk_episodes_drama_id_dramas'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_episodes')),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_0900_ai_ci'
    )
    op.create_index(op.f('ix_episodes_drama_id'), 'episodes', ['drama_id'], unique=False)

    op.create_table('scripts',
        sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), autoincrement=True, nullable=False),
        sa.Column('episode_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        # 逻辑指针(不加 FK):避免与 script_versions.script_id 循环。
        sa.Column('current_version_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=True),
        sa.Column('updated_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.Column('created_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], name=op.f('fk_scripts_episode_id_episodes'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_scripts')),
        sa.UniqueConstraint('episode_id', name=op.f('uq_scripts_episode_id')),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_0900_ai_ci'
    )

    op.create_table('script_versions',
        sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), autoincrement=True, nullable=False),
        sa.Column('script_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('content', mysql.MEDIUMTEXT(), nullable=False),
        sa.Column('format', sa.Enum('plain', 'markdown', 'fountain'), server_default=sa.text("'markdown'"), nullable=False),
        sa.Column('source', sa.Enum('input', 'optimize'), nullable=False),
        sa.Column('created_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.ForeignKeyConstraint(['script_id'], ['scripts.id'], name=op.f('fk_script_versions_script_id_scripts'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_script_versions')),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_0900_ai_ci'
    )
    op.create_index(op.f('ix_script_versions_script_id'), 'script_versions', ['script_id'], unique=False)

    # ---- 剧集角色域 ----
    op.create_table('episode_characters',
        sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), autoincrement=True, nullable=False),
        sa.Column('episode_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('role_type', sa.String(length=32), nullable=True),
        sa.Column('persona', sa.String(length=512), nullable=True),
        sa.Column('motivation', sa.String(length=512), nullable=True),
        sa.Column('traits', mysql.JSON(), nullable=True),
        sa.Column('appearance_desc', sa.String(length=1024), nullable=True),
        # M2:source 仅 preset|analysis(library 留 M4;image_media_id 留 M3)。
        sa.Column('source', sa.Enum('preset', 'analysis'), server_default=sa.text("'preset'"), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('updated_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.Column('created_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], name=op.f('fk_episode_characters_episode_id_episodes'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_episode_characters')),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_0900_ai_ci'
    )
    op.create_index(op.f('ix_episode_characters_episode_id'), 'episode_characters', ['episode_id'], unique=False)

    # ---- 分析产物域 ----
    op.create_table('analyses',
        sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), autoincrement=True, nullable=False),
        sa.Column('episode_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('status', sa.Enum('pending', 'running', 'succeeded', 'failed'), nullable=False),
        sa.Column('result', mysql.JSON(), nullable=True),
        sa.Column('config_snapshot', mysql.JSON(), nullable=True),
        # D11:发起拆解时的剧本版本(物理 FK)。
        sa.Column('script_version_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('updated_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.Column('created_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], name=op.f('fk_analyses_episode_id_episodes'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['script_version_id'], ['script_versions.id'], name=op.f('fk_analyses_script_version_id_script_versions'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_analyses')),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_0900_ai_ci'
    )
    op.create_index(op.f('ix_analyses_episode_id'), 'analyses', ['episode_id'], unique=False)
    op.create_index(op.f('ix_analyses_script_version_id'), 'analyses', ['script_version_id'], unique=False)

    op.create_table('shots',
        sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), autoincrement=True, nullable=False),
        sa.Column('analysis_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('episode_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(length=1024), nullable=False),
        sa.Column('shot_type', sa.Enum('wide', 'medium', 'close', 'extreme_close'), nullable=True),
        sa.Column('scene', sa.String(length=128), nullable=True),
        sa.Column('plot_point', sa.String(length=255), nullable=True),
        sa.Column('dialogue', sa.Text(), nullable=True),
        sa.Column('target_duration', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('camera_move', sa.String(length=64), nullable=True),
        sa.Column('related_plotline', sa.String(length=128), nullable=True),
        sa.Column('related_conflict', sa.String(length=128), nullable=True),
        sa.Column('updated_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.Column('created_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], name=op.f('fk_shots_analysis_id_analyses'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], name=op.f('fk_shots_episode_id_episodes'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_shots')),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_0900_ai_ci'
    )
    op.create_index(op.f('ix_shots_analysis_id'), 'shots', ['analysis_id'], unique=False)
    # 复合索引 (episode_id, seq):命名按 convention ix_%(column_0_label)s 取首列(D12 约定)。
    op.create_index(op.f('ix_shots_episode_id'), 'shots', ['episode_id', 'seq'], unique=False)

    op.create_table('shot_characters',
        sa.Column('shot_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('episode_character_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('role_in_shot', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['shot_id'], ['shots.id'], name=op.f('fk_shot_characters_shot_id_shots'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['episode_character_id'], ['episode_characters.id'], name=op.f('fk_shot_characters_episode_character_id_episode_characters'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('shot_id', 'episode_character_id', name=op.f('pk_shot_characters')),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_0900_ai_ci'
    )

    # ---- 任务域 ----
    op.create_table('tasks',
        sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=False),
        sa.Column('episode_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql'), nullable=True),
        sa.Column('type', sa.Enum('optimize', 'analyze', 'image', 'video', 'render'), nullable=False),
        sa.Column('status', sa.Enum('pending', 'running', 'succeeded', 'failed', 'canceled', 'interrupted'), nullable=False),
        sa.Column('progress', mysql.TINYINT(unsigned=True), server_default=sa.text('0'), nullable=False),
        sa.Column('stage', sa.String(length=64), nullable=True),
        sa.Column('trigger', sa.Enum('single', 'batch'), server_default=sa.text("'single'"), nullable=False),
        sa.Column('input_snapshot', mysql.JSON(), nullable=True),
        sa.Column('output_refs', mysql.JSON(), nullable=True),
        sa.Column('error', mysql.JSON(), nullable=True),
        sa.Column('started_at', mysql.DATETIME(fsp=3), nullable=True),
        sa.Column('finished_at', mysql.DATETIME(fsp=3), nullable=True),
        sa.Column('created_at', mysql.DATETIME(fsp=3), server_default=sa.text('CURRENT_TIMESTAMP(3)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_tasks_user_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], name=op.f('fk_tasks_episode_id_episodes'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_tasks')),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_0900_ai_ci'
    )
    # 复合索引 (user_id, status, created_at):命名按 convention 取首列(D12 约定)。
    op.create_index(op.f('ix_tasks_user_id'), 'tasks', ['user_id', 'status', 'created_at'], unique=False)
    op.create_index(op.f('ix_tasks_episode_id'), 'tasks', ['episode_id'], unique=False)


def downgrade() -> None:
    # MySQL:drop_table 会级联删除表上的索引与外键,故直接删表即可(见 model_configs 迁移同款注释)。
    # 删除顺序严格满足 FK(引用者先于被引用者):tasks/shots/analyses/scripts/episode_characters
    # 均引用 episodes,须在 episodes 之前删;scripts 引用 dramas,须在 dramas 之前删。
    op.drop_table('shot_characters')
    op.drop_table('tasks')
    op.drop_table('shots')
    op.drop_table('analyses')
    op.drop_table('episode_characters')
    op.drop_table('script_versions')
    op.drop_table('scripts')
    op.drop_table('episodes')
    op.drop_table('dramas')
