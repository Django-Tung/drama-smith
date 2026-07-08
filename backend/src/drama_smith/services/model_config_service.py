"""模型配置用例编排(BYOK,`design.md` D3–D9)。

事务边界在此(M0 D14):用例内显式 `commit`;`get_session` 仅 yield,异常时请求级会话
关闭即回滚。只向下依赖 `core` / `db` / `llm`。

用例:
- `create_config`:白名单校验 → 信封加密落库 → 首条自动 active(D4)。
- `update_config`:`api_key` 缺省不动加密列(D8);给出则全量重封。
- `delete_config`:删 active 行按 D4 —— 同 purpose 有兄弟须显式 `new_active_id`(否则 409),
  0 条则直接删(text 经 `has_active_text` 自然回未配态,image/video 仅禁用)。
- `activate_config`:单事务翻转(D3)。
- `test_config`:解密 Key → `factory.build` → `probe()` → 回写 `last_tested_at`;
  鉴权失败置 `invalid` + 抛 `ProviderAuthFailed`(D7),限流/超时抛 `RateLimited`(D6)。
- `require_active_text`:M2 分析门禁预留,本期不被调用。
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.core import crypto
from drama_smith.core.errors import (
    Conflict,
    ModelNotConfigured,
    NotFound,
    ProviderAuthFailed,
    RateLimited,
)
from drama_smith.db.base import utcnow
from drama_smith.db.models import ModelConfig
from drama_smith.db.repositories import model_config_repo
from drama_smith.db.repositories.model_config_repo import _UNSET
from drama_smith.llm import factory as llm_factory
from drama_smith.llm.base import (
    ImageModel,
    ModelConfigSnapshot,
    ProbeNotSupported,
    TextModel,
    VideoModel,
    validate_provider,
)

# 自检有限重试上限(D6「有限重试,不无限阻塞」);仅对瞬时限流重试,鉴权错不重试。
# M1 为单次 /models 探测,退避策略留 M2。
_MAX_PROBE_ATTEMPTS = 2

# 接缝构造器类型;service 解密明文后注入,保持 `llm/` 不碰 crypto。
ModelBuilder = Callable[[ModelConfigSnapshot, str], TextModel | ImageModel | VideoModel]


def _envelope(config: ModelConfig) -> crypto.Envelope:
    """从持久化行还原信封(两个自包含 blob)。"""
    return crypto.Envelope(key_blob=config.api_key_ciphertext, dek_blob=config.dek_ciphertext)


def _snapshot(config: ModelConfig) -> ModelConfigSnapshot:
    """从持久化行构造调用接缝所需的配置快照(不含明文 Key)。"""
    return ModelConfigSnapshot(
        purpose=config.purpose,
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        params=config.params,
        provider_options=config.provider_options,
    )


async def list_configs(
    session: AsyncSession, user_id: int, purpose: str | None = None
) -> list[ModelConfig]:
    """列当前用户配置(可选 purpose 过滤)。"""
    return await model_config_repo.list_configs(session, user_id, purpose)


async def get_config(session: AsyncSession, user_id: int, config_id: int) -> ModelConfig:
    """取单条(强制 user_id 过滤;越权 / 不存在 → `NotFound`)。"""
    return await model_config_repo.get(session, user_id, config_id)


async def create_config(
    session: AsyncSession,
    user_id: int,
    *,
    purpose: str,
    provider: str,
    model: str,
    api_key: str,
    mek: bytes,
    base_url: str | None = None,
    params: dict[str, object] | None = None,
    provider_options: dict[str, object] | None = None,
) -> ModelConfig:
    """新建:白名单校验 → 信封加密 → 首条自动 active(D4)→ 提交。

    越界 `(purpose, provider)` → `ValueError`(API 层 schema 应先 422 拦截,此为兜底)。
    """
    validate_provider(purpose, provider)
    env = crypto.encrypt(api_key, mek)
    is_first_active = (await model_config_repo.count_active(session, user_id, purpose)) == 0
    config = await model_config_repo.create(
        session,
        user_id,
        purpose=purpose,
        provider=provider,
        model=model,
        api_key_ciphertext=env.key_blob,
        dek_ciphertext=env.dek_blob,
        api_key_masked=crypto.mask_key(api_key),
        is_active=is_first_active,
        base_url=base_url,
        params=params,
        provider_options=provider_options,
    )
    await session.commit()
    return config


async def update_config(
    session: AsyncSession,
    user_id: int,
    config_id: int,
    *,
    mek: bytes,
    provider: object = _UNSET,
    model: object = _UNSET,
    base_url: object = _UNSET,
    params: object = _UNSET,
    provider_options: object = _UNSET,
    api_key: object = _UNSET,
) -> ModelConfig:
    """PUT 更新:`api_key` 缺省(= `_UNSET`)不动加密列;给出则全量重封(D8)。

    其余字段 `_UNSET` 表不改动,显式 `None` 表清空(如 `base_url`)。`is_active` 翻转走
    `activate_config`,不在此。改 provider 时按新组合复校白名单。
    """
    config = await model_config_repo.get(session, user_id, config_id)
    effective_provider = provider if provider is not _UNSET else config.provider
    validate_provider(config.purpose, str(effective_provider))

    key_blob: object = _UNSET
    dek_blob: object = _UNSET
    masked: object = _UNSET
    if api_key is not _UNSET:
        env = crypto.encrypt(str(api_key), mek)
        key_blob, dek_blob, masked = env.key_blob, env.dek_blob, crypto.mask_key(str(api_key))

    updated = await model_config_repo.update(
        session,
        config,
        provider=provider,  # type: ignore[arg-type]
        model=model,  # type: ignore[arg-type]
        base_url=base_url,  # type: ignore[arg-type]
        params=params,  # type: ignore[arg-type]
        provider_options=provider_options,  # type: ignore[arg-type]
        api_key_ciphertext=key_blob,  # type: ignore[arg-type]
        dek_ciphertext=dek_blob,  # type: ignore[arg-type]
        api_key_masked=masked,  # type: ignore[arg-type]
    )
    await session.commit()
    return updated


async def activate_config(session: AsyncSession, user_id: int, config_id: int) -> ModelConfig:
    """置指定配置为当前 active(单事务翻转,D3)→ 提交。"""
    config = await model_config_repo.activate(session, user_id, config_id)
    await session.commit()
    return config


async def delete_config(
    session: AsyncSession,
    user_id: int,
    config_id: int,
    *,
    new_active_id: int | None = None,
) -> None:
    """删除(D4):删 active 且同 purpose 仍有兄弟 → 须显式 `new_active_id`(否则 409)。

    给定 `new_active_id` 时:先 activate 继任(单事务内旧 active 先翻 0,避免 UNIQUE 冲突),
    再删旧行。继任须属同 `(user_id, purpose)` 且非被删行本身,否则 `NotFound`。
    """
    config = await model_config_repo.get(session, user_id, config_id)
    if config.is_active:
        siblings = [
            c
            for c in await model_config_repo.list_configs(session, user_id, config.purpose)
            if c.id != config_id
        ]
        if siblings:
            if new_active_id is None:
                raise Conflict(
                    "Deleting the active configuration requires an explicit successor",
                    details={"reason": "invalid_state"},
                )
            if not any(c.id == new_active_id for c in siblings):
                raise NotFound("Successor configuration not found within the same purpose")
            # 先提升继任(旧 active 经 bulk update 翻 0),再删旧行 —— 全程至多一条 active。
            await model_config_repo.activate(session, user_id, new_active_id)
    await model_config_repo.delete(session, config)
    await session.commit()


async def test_config(
    session: AsyncSession,
    user_id: int,
    config_id: int,
    *,
    mek: bytes,
    model_factory: ModelBuilder | None = None,
) -> ModelConfig:
    """自检(FR-C5/D7):解密 Key → `factory.build` → `probe()` → 回写 `last_tested_at`。

    - 仅 text/image 有零成本探测路径(D6);video 自检本期不暴露(M3)。
    - provider 401/403 → 置 `status=invalid` + 抛 `ProviderAuthFailed`(D7)。
    - 429/5xx/超时 → 有限重试后抛 `RateLimited`,不置 invalid(瞬态,非坏 key)。
    - 无 `/models` 端点 → `ProbeNotSupported` 降级,视为通过(FR-C3 允许降级)。
    """
    config = await model_config_repo.get(session, user_id, config_id)
    plaintext_key = crypto.decrypt(_envelope(config), mek)
    model = (model_factory or llm_factory.build)(_snapshot(config), plaintext_key)

    config.last_tested_at = utcnow()
    try:
        if not isinstance(model, (TextModel, ImageModel)):
            # video 等(M3)无 probe 路径的用途 → 降级,不自检
            raise ProbeNotSupported("Self-test is only available for text/image models")
        await _probe_with_retry(model)
    except ProbeNotSupported:
        pass  # 无 probe 路径 / provider 无 /models 端点 → 降级,不计失败
    except ProviderAuthFailed:
        await model_config_repo.set_status(session, user_id, config_id, "invalid")
        await session.commit()
        raise
    except RateLimited:
        await session.commit()
        raise
    # 成功 / 降级(ProbeNotSupported)→ 复位为 `active`(M1 修复:此前成功后不把 invalid 改回,
    # 一旦因瞬态被判 invalid 便永不恢复)。瞬态 RateLimited 不改 status(非坏 key)。
    await model_config_repo.set_status(session, user_id, config_id, "active")
    await session.commit()
    return config


async def _probe_with_retry(model: TextModel | ImageModel) -> None:
    """有限重试探测:仅对 `RateLimited`(瞬态)重试;鉴权错 / 降级直接冒泡。

    M1 单次重试不退避;M2 引入指数退避。`-> None` 故循环(逻辑上不可达)落空即返回 None。
    """
    for attempt in range(_MAX_PROBE_ATTEMPTS):
        try:
            await model.probe()
            return
        except RateLimited:
            if attempt == _MAX_PROBE_ATTEMPTS - 1:
                raise  # 重试用尽 → 冒泡(test_config 据此不置 invalid)
            # 瞬态限流:立即重试一次


async def require_active_text(session: AsyncSession, user_id: int) -> None:
    """M2 分析门禁预留:无 active 文本配置 → `ModelNotConfigured`。本期不被调用(D11)。"""
    if not await model_config_repo.has_active_text(session, user_id):
        raise ModelNotConfigured()


async def has_text_configured(session: AsyncSession, user_id: int) -> bool:
    """`GET /api/me` 完成度信号:是否存在 active 文本配置(design D9)。"""
    return await model_config_repo.has_active_text(session, user_id)
