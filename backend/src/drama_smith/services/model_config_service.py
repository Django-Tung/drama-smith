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
- `require_active_text`:M2 分析门禁 —— 取 active 且 `status='active'` 的文本配置,无则
  `ModelNotConfigured`;返回配置行(供 `build_text_model_from_config` 解密构造 TextModel)。
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


async def require_active_text(session: AsyncSession, user_id: int) -> ModelConfig:
    """M2 分析门禁:取 active 且 `status='active'` 的文本配置;无 → `ModelNotConfigured`。

    返回配置行(供 `build_active_text_model` 解密 Key 构造 TextModel)。比仅判存在多验
    `status`:被自检判 `invalid` 的配置不可用于分析(D8)。
    """
    config = await model_config_repo.get_active_text_config(session, user_id)
    if config is None:
        raise ModelNotConfigured()
    return config


def build_text_model_from_config(
    config: ModelConfig,
    mek: bytes,
    *,
    model_factory: ModelBuilder | None = None,
) -> TextModel:
    """从**已加载**的配置行构造 `TextModel`(同步、不再查 DB;供 work 闭包用**冻结的**配置,D9)。

    明文 Key 仅驻返回 adapter 的内存(D8);`model_factory` 供测试注入替身(镜像 `test_config`)。
    发起拆解 / 优化时 service 经 `require_active_text` 取 config 行、work 闭包捕获之 —— 运行期
    用户改 active 配置不影响在途任务(config 已冻结,见 D9)。
    """
    plaintext_key = crypto.decrypt(_envelope(config), mek)
    model = (model_factory or llm_factory.build)(_snapshot(config), plaintext_key)
    if not isinstance(model, TextModel):
        # 不可达:`require_active_text` 取的是 purpose='text' 行,factory 据此产 TextModel。
        raise ModelNotConfigured(details={"reason": "active_config_not_text"})
    return model


async def mark_config_invalid(
    session_factory: async_sessionmaker[AsyncSession], user_id: int, config_id: int
) -> None:
    """后台路径(work 闭包)用:开自己的 session 把配置置 `invalid` + commit(D8 鉴权失败)。

    work 在请求 session 之外跑,需自建 session 落 status;与 `test_config` 的请求内路径互补。
    """
    async with session_factory() as session:
        await model_config_repo.set_status(session, user_id, config_id, "invalid")
        await session.commit()


async def has_text_configured(session: AsyncSession, user_id: int) -> bool:
    """`GET /api/me` 完成度信号:是否存在 active 文本配置(design D9)。"""
    return await model_config_repo.has_active_text(session, user_id)
