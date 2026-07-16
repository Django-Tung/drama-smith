"""模型配置仓储(BYOK)。

事务边界在 services 层(`design.md` D14):本层只查询 / `add` / `flush`,不 commit。
所有读写一律带 `user_id` 强制过滤(承接 M0 D6 多租户隔离):越权访问他人配置 → `NotFound`,
不泄露存在性。「每用途恰一条 active」由生成列 `active_key` + UNIQUE 在 DB 层兜底,
`activate` 在单事务内先翻转旧 active 再置新(design D3)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core.errors import Conflict, NotFound
from drama_smith.db.models import ModelConfig

# 「未提供」哨兵:与显式 `None`(清空 base_url 等)区分,PUT 缺省字段时据此跳过。
_UNSET: Any = object()


async def list_configs(
    session: AsyncSession, user_id: int, purpose: str | None = None
) -> list[ModelConfig]:
    """列当前用户的配置;`purpose` 可选过滤。"""
    stmt = select(ModelConfig).where(ModelConfig.user_id == user_id)
    if purpose is not None:
        stmt = stmt.where(ModelConfig.purpose == purpose)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get(session: AsyncSession, user_id: int, config_id: int) -> ModelConfig:
    """按 id 取配置(强制 `user_id` 过滤);无命中 / 越权 → `NotFound`。"""
    stmt = select(ModelConfig).where(
        ModelConfig.id == config_id, ModelConfig.user_id == user_id
    )
    config: ModelConfig | None = (await session.execute(stmt)).scalar_one_or_none()
    if config is None:
        raise NotFound("Model configuration not found")
    return config


async def create(
    session: AsyncSession,
    user_id: int,
    *,
    purpose: str,
    provider: str,
    model: str,
    api_key_ciphertext: bytes,
    dek_ciphertext: bytes,
    api_key_masked: str,
    is_active: bool,
    base_url: str | None = None,
    params: dict[str, Any] | None = None,
    provider_options: dict[str, Any] | None = None,
) -> ModelConfig:
    """新建配置(`is_active` 由 service 按 D4 决定)。

    `flush` 即时触发 `active_key` UNIQUE:若与既有 active 冲突(竞态)→ `Conflict`。
    """
    config = ModelConfig(
        user_id=user_id,
        purpose=purpose,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_ciphertext=api_key_ciphertext,
        dek_ciphertext=dek_ciphertext,
        api_key_masked=api_key_masked,
        params=params,
        provider_options=provider_options,
        is_active=is_active,
    )
    session.add(config)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict("Model configuration conflicts with an active one") from exc
    await session.refresh(config)  # 回读 server_default 与生成列
    return config


async def update(
    session: AsyncSession,
    config: ModelConfig,
    *,
    provider: str | None = _UNSET,
    model: str | None = _UNSET,
    base_url: str | None = _UNSET,
    params: dict[str, Any] | None = _UNSET,
    provider_options: dict[str, Any] | None = _UNSET,
    api_key_ciphertext: bytes | None = _UNSET,
    dek_ciphertext: bytes | None = _UNSET,
    api_key_masked: str | None = _UNSET,
) -> ModelConfig:
    """按字段更新;`_UNSET` 表示不改动(故 PUT 不带新 key 时加密列原样不动,D8)。

    显式 `None` 表示清空该可空字段(如 `base_url`)。`is_active` 翻转走 `activate`,不在此。
    """
    provided: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "params": params,
        "provider_options": provider_options,
        "api_key_ciphertext": api_key_ciphertext,
        "dek_ciphertext": dek_ciphertext,
        "api_key_masked": api_key_masked,
    }
    for name, value in provided.items():
        if value is not _UNSET:
            setattr(config, name, value)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict("Model configuration conflict") from exc
    return config


async def delete(session: AsyncSession, config: ModelConfig) -> None:
    """删除已加载的配置对象(调用方已按 D4 处理 active 规则)。"""
    await session.delete(config)
    await session.flush()


async def count_active(session: AsyncSession, user_id: int, purpose: str) -> int:
    """该 `(user_id, purpose)` 当前 active 配置数(D4「首条自动 active」判定用)。"""
    stmt = (
        select(func.count())
        .select_from(ModelConfig)
        .where(
            ModelConfig.user_id == user_id,
            ModelConfig.purpose == purpose,
            ModelConfig.is_active.is_(True),
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def has_active_text(session: AsyncSession, user_id: int) -> bool:
    """该用户是否存在 active 文本配置(`GET /api/me` 完成度信号,D9)。"""
    stmt = select(
        exists().where(
            ModelConfig.user_id == user_id,
            ModelConfig.purpose == "text",
            ModelConfig.is_active.is_(True),
        )
    )
    return bool((await session.execute(stmt)).scalar())


async def get_active_text_config(
    session: AsyncSession, user_id: int
) -> ModelConfig | None:
    """取该用户当前 active 且 `status='active'` 的文本配置;无则 None(M2 分析门禁用)。

    比 `has_active_text` 多一道 `status='active'` 过滤:被自检判 `invalid` 的配置不可用于
    分析(`design.md` D8 门禁)。每用途至多一条 active(UNIVE `active_key` 兜底),故
    `scalar_one_or_none` 安全。
    """
    stmt = select(ModelConfig).where(
        ModelConfig.user_id == user_id,
        ModelConfig.purpose == "text",
        ModelConfig.is_active.is_(True),
        ModelConfig.status == "active",
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_active_image_config(
    session: AsyncSession, user_id: int
) -> ModelConfig | None:
    """取该用户当前 active 且 `status='active'` 的图片配置;无则 None(M3 形象图门禁用)。

    与 `get_active_text_config` 同范式(镜像 text);`invalid` 配置不可用于生成(D8)。
    """
    stmt = select(ModelConfig).where(
        ModelConfig.user_id == user_id,
        ModelConfig.purpose == "image",
        ModelConfig.is_active.is_(True),
        ModelConfig.status == "active",
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def has_active_image(session: AsyncSession, user_id: int) -> bool:
    """该用户是否存在 active 图片配置(`GET /api/me` 完成度信号,镜像 `has_active_text`)。"""
    stmt = select(
        exists().where(
            ModelConfig.user_id == user_id,
            ModelConfig.purpose == "image",
            ModelConfig.is_active.is_(True),
        )
    )
    return bool((await session.execute(stmt)).scalar())


async def activate(session: AsyncSession, user_id: int, config_id: int) -> ModelConfig:
    """单事务内:先把同 `(user_id, purpose)` 的其它 active 置 0,再置目标为 1(design D3)。

    DB 的 `active_key` UNIQUE 为兜底;先翻旧再置新即不冲突。目标不存在 / 越权 → `NotFound`。
    """
    config = await get(session, user_id, config_id)
    await session.execute(
        sql_update(ModelConfig)
        .where(
            ModelConfig.user_id == user_id,
            ModelConfig.purpose == config.purpose,
            ModelConfig.is_active.is_(True),
            ModelConfig.id != config_id,
        )
        .values(is_active=False)
    )
    config.is_active = True
    try:
        await session.flush()
    except IntegrityError as exc:  # 极端竞态兜底
        raise Conflict("Model configuration conflicts with an active one") from exc
    return config


async def set_status(
    session: AsyncSession, user_id: int, config_id: int, status: str
) -> None:
    """`UPDATE ... WHERE id AND user_id`:运行期鉴权失败 → `status='invalid'`(FR-C5, D7)。"""
    await session.execute(
        sql_update(ModelConfig)
        .where(ModelConfig.id == config_id, ModelConfig.user_id == user_id)
        .values(status=status)
    )
