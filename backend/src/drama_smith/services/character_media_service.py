"""剧集角色形象图用例编排(M3;design D5/D8)。

三种操作:
- `get_portrait`(同步读):取角色当前选用形象图 + 签名 URL;无 → None(端点 204)。
- `upload_portrait`(同步):multipart → Pillow 校验/超 1 MiB 压缩 → `FileStore.save` → 落 `media`
  (`source='upload'`, `selected=True`)+ 更新 `character.image_media_id`(D3 逻辑指针)。
- `generate_portrait`(异步 image 任务):门禁(active image 配置 + 角色已填 `appearance_desc`)→
  建 task → executor 后台 work 闭包:构 `ImageModel`(冻结 config)→ `generate(prompt)` → 下载远程
  图 → `FileStore.save` → 落 `media`(`source='generate'`) + 更新指针。镜像 `analysis_service` 范式。

事务边界:发起路径用请求 session(create task → commit);work 闭包开自己的
session(`get_session_factory()`)。
`FileStore` 经 work 闭包捕获注入(D4,executor 构造签名不变)。鉴权失败经 `mark_config_invalid` 置配置
`invalid`(D8)。prompt 构造留本模块(不进 `analysis/`/`graphs/`/`tasks/`,守 NFR-2)。
"""

from __future__ import annotations

import asyncio
import base64
import logging
from io import BytesIO
from typing import Any

import httpx
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drama_smith.core.errors import (
    InvalidState,
    MediaInvalid,
    MediaTooLarge,
    ProviderAuthFailed,
    RateLimited,
)
from drama_smith.db.base import get_session_factory
from drama_smith.db.models import EpisodeCharacter, Media, Task
from drama_smith.db.repositories import episode_character_repo, media_repo, task_repo
from drama_smith.services import character_service, model_config_service
from drama_smith.services.model_config_service import ModelBuilder
from drama_smith.storage import FileStore, build_signed_url
from drama_smith.tasks import ProgressCallback, TaskExecutor, Work

logger = logging.getLogger("drama_smith.character_media_service")

# 软压缩阈(FR-L4):落盘超 1 MiB 则 Pillow 递降 JPEG 质量重压至 ≤ 1 MiB。
_1_MIB = 1024 * 1024
_COMPRESS_QUALITIES = (95, 90, 85, 80, 70, 60, 50, 40)

# 远程图下载:超时 + 瞬态重试(429/5xx/超时);其余 4xx 立即抛。
_DOWNLOAD_TIMEOUT = 30.0
_DOWNLOAD_RETRIES = 2
_BASE_DELAY = 1.0

# Pillow format → (content_type, ext);上传 / 生成两条路径共用(以实际解码格式为准,不信客户端 ct)。
_FMT_TO_CT: dict[str, tuple[str, str]] = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}


# ---- 同步读:当前形象图 ----


async def get_portrait(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    character_id: int,
    *,
    file_store: FileStore,
) -> dict[str, Any] | None:
    """取角色当前选用形象图 + 短期签名 URL;无形象图 → None(端点据此 204)。

    归属经 `character_service.get_character` 校验(越权 / 不存在 → `NotFound`)。
    """
    await character_service.get_character(session, user_id, episode_id, character_id)
    media = await media_repo.get_current_for_owner(
        session, user_id, owner_type="character", owner_id=character_id
    )
    if media is None:
        return None
    token, exp = file_store.sign(media.id)
    return _portrait_view(media, token, exp)


# ---- 同步:上传 ----


async def upload_portrait(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    character_id: int,
    *,
    file_store: FileStore,
    data: bytes,
    max_bytes: int,
) -> dict[str, Any]:
    """上传形象图(同步):硬上限校验 → Pillow 解码/取尺寸 → 超 1 MiB 重压 → 落盘 + 落库。

    - 超过 `max_bytes`(`DS_MEDIA_UPLOAD_MAX_BYTES`)→ `MediaTooLarge`(413,防滥用)。
    - 解码失败 / 非图片 / 非支持格式 → `MediaInvalid`(422;以实际格式为准,不信客户端 ct)。
    - 超 1 MiB → 递降 JPEG 质量重压至 ≤ 1 MiB(FR-L4);不拒绝。
    """
    if len(data) > max_bytes:
        raise MediaTooLarge(details={"max_bytes": max_bytes, "size": len(data)})
    character = await character_service.get_character(session, user_id, episode_id, character_id)
    img, content_type, ext = _decode_image(data)
    width, height = img.width, img.height
    if len(data) > _1_MIB:
        data = _recompress_jpeg(img)
        content_type, ext = "image/jpeg", "jpg"

    storage_key = file_store.save(user_id=user_id, data=data, ext=ext)
    media = await media_repo.create(
        session,
        user_id,
        kind="image",
        owner_type="character",
        owner_id=character_id,
        source="upload",
        storage_key=storage_key,
        content_type=content_type,
        size_bytes=len(data),
        width=width,
        height=height,
        selected=True,
    )
    await episode_character_repo.set_image_media(session, character, media.id)
    await session.commit()
    token, exp = file_store.sign(media.id)
    return _portrait_view(media, token, exp)


# ---- 异步:AI 生成 ----


async def generate_portrait(
    session: AsyncSession,
    user_id: int,
    episode_id: int,
    character_id: int,
    *,
    mek: bytes,
    file_store: FileStore,
    executor: TaskExecutor,
    model_factory: ModelBuilder | None = None,
) -> Task:
    """发起形象图 AI 生成:门禁 → 建 image 任务 → 提交执行器 → 返回 task(202)。

    - 归属:`character_service.get_character`(`NotFound`)。
    - 门禁:`require_active_image`(`ModelNotConfigured`);角色未填 `appearance_desc` →
      `InvalidState`(details `reason='appearance_required'`,D8「必须填角色相关字段」)。
    `model_factory` 透传给 work 闭包,供测试注入替身(经 `build_image_model_from_config`)。
    config 在发起时冻结(D9:运行期改 active 配置不影响在途任务)。
    """
    character = await character_service.get_character(session, user_id, episode_id, character_id)
    config = await model_config_service.require_active_image(session, user_id)
    if not character.appearance_desc or not character.appearance_desc.strip():
        raise InvalidState(
            "Character requires an appearance description for AI portrait generation",
            details={"reason": "appearance_required"},
        )

    prompt = _build_portrait_prompt(character)
    task = await task_repo.create(
        session,
        user_id,
        episode_id=episode_id,
        type="image",
        input_snapshot={
            "character_id": character_id,
            "model": {
                "provider": config.provider,
                "model": config.model,
                "base_url": config.base_url,
            },
        },
    )
    await session.commit()

    work = _make_generate_work(
        user_id=user_id,
        character_id=character_id,
        config=config,
        mek=mek,
        prompt=prompt,
        file_store=file_store,
        model_factory=model_factory,
    )
    await executor.submit(task.id, user_id, work)
    return task


# ---- work 闭包 + 落库(executor 后台跑,开自己的 session)----


def _make_generate_work(
    *,
    user_id: int,
    character_id: int,
    config: Any,
    mek: bytes,
    prompt: str,
    file_store: FileStore,
    model_factory: ModelBuilder | None,
) -> Work:
    """构造 image generate 的 work 闭包:构模型 → 生成 → 下载 → 落盘 → 落库。

    `file_store` / `mek` / 冻结 config 经闭包捕获(D4:executor 构造签名不变)。鉴权失败置配置
    `invalid`(D8);其余异常冒泡 → 执行器落 task `failed`(`error.code` 按异常映射)。
    """
    sf = get_session_factory()

    async def work(progress_cb: ProgressCallback) -> dict[str, Any] | None:
        image_model = model_config_service.build_image_model_from_config(
            config, mek, model_factory=model_factory
        )
        try:
            await progress_cb(10, "generating")
            remote_url = await image_model.generate(prompt)
            await progress_cb(60, "downloading")
            data = await _download_image(remote_url)
            content_type, ext, width, height = _probe_image(data)
            await progress_cb(80, "persisting")
            storage_key = file_store.save(user_id=user_id, data=data, ext=ext)
            media_id = await _persist_portrait(
                sf,
                user_id,
                character_id,
                storage_key=storage_key,
                content_type=content_type,
                size_bytes=len(data),
                width=width,
                height=height,
            )
            await progress_cb(100, "done")
            return {"media_id": media_id}
        except ProviderAuthFailed:
            await model_config_service.mark_config_invalid(sf, user_id, config.id)
            raise

    return work


async def _persist_portrait(
    sf: async_sessionmaker[AsyncSession],
    user_id: int,
    character_id: int,
    *,
    storage_key: str,
    content_type: str,
    size_bytes: int,
    width: int,
    height: int,
) -> int:
    """后台落库(单事务):建 media(`source='generate'`, `selected=True`,旧图翻 False)+ 更新指针。

    重载角色(归属校验)+ `media_repo.create`(内含旧 selected 翻 False)+ `set_image_media`。
    """
    async with sf() as session:
        character = await episode_character_repo.get(session, user_id, character_id)
        media = await media_repo.create(
            session,
            user_id,
            kind="image",
            owner_type="character",
            owner_id=character_id,
            source="generate",
            storage_key=storage_key,
            content_type=content_type,
            size_bytes=size_bytes,
            width=width,
            height=height,
            selected=True,
        )
        await episode_character_repo.set_image_media(session, character, media.id)
        await session.commit()
        return media.id


# ---- 辅助:解码 / 压缩 / 探测 / 下载 / prompt / 视图 ----


def _decode_image(data: bytes) -> tuple[Image.Image, str, str]:
    """解码字节为 PIL Image + 推断 (content_type, ext);失败 / 非图片 → `MediaInvalid`。"""
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Exception as exc:  # noqa: BLE001 — Pillow 抛多种格式异常,统一收敛为 MediaInvalid
        raise MediaInvalid("Uploaded content is not a valid image") from exc
    fmt = (img.format or "").upper()
    if fmt not in _FMT_TO_CT:
        raise MediaInvalid(f"Unsupported image format: {fmt or 'unknown'}")
    content_type, ext = _FMT_TO_CT[fmt]
    return img, content_type, ext


def _recompress_jpeg(img: Image.Image) -> bytes:
    """递降 JPEG 质量重压至 ≤ 1 MiB;耗尽质量梯度则返回最低质量结果(尽力压缩)。"""
    rgb = img if img.mode in ("RGB", "L") else img.convert("RGB")
    buf = BytesIO()
    for quality in _COMPRESS_QUALITIES:
        buf = BytesIO()
        rgb.save(buf, format="JPEG", quality=quality, optimize=True)
        if buf.tell() <= _1_MIB:
            return buf.getvalue()
    return buf.getvalue()


def _probe_image(data: bytes) -> tuple[str, str, int, int]:
    """探测下载字节:(content_type, ext, width, height);非图片 → `MediaInvalid`。"""
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise MediaInvalid("Downloaded content is not a valid image") from exc
    fmt = (img.format or "").upper()
    if fmt not in _FMT_TO_CT:
        raise MediaInvalid(f"Unsupported downloaded image format: {fmt or 'unknown'}")
    content_type, ext = _FMT_TO_CT[fmt]
    return content_type, ext, img.width, img.height


async def _download_image(url: str) -> bytes:
    """下载远程生成图(http(s) 或 data URI);瞬态错误有限重试,不可恢复立即抛。

    - `data:` URI(base64,部分供应商 b64 返回)→ 直接解码。
    - 429/5xx/超时 → 1+`_DOWNLOAD_RETRIES` 次指数退避,耗尽抛 `RateLimited`。
    - 其余 4xx / 坏 data URI → `MediaInvalid`(供应商返回坏 URL / 权限 / 损坏内容)。
    """
    if url.startswith("data:"):
        _, _, b64 = url.partition(",")
        try:
            return base64.b64decode(b64)
        except Exception as exc:  # noqa: BLE001
            raise MediaInvalid("Invalid image data URI") from exc

    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        for attempt in range(_DOWNLOAD_RETRIES + 1):
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.content
            except httpx.TimeoutException as exc:
                last_exc = exc
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if not (status == 429 or status >= 500):
                    raise MediaInvalid(f"Image URL returned HTTP {status}") from exc
                last_exc = exc
            if attempt < _DOWNLOAD_RETRIES:
                await asyncio.sleep(_BASE_DELAY * (2**attempt))
    raise RateLimited("Failed to download generated image after retries") from last_exc


def _build_portrait_prompt(c: EpisodeCharacter) -> str:
    """构造形象图 prompt:appearance_desc 为主,辅以 name/role_type/persona(D8)。"""
    parts: list[str] = []
    if c.appearance_desc:
        parts.append(f"角色外形:{c.appearance_desc.strip()}")
    if c.name:
        parts.append(f"姓名:{c.name}")
    if c.role_type:
        parts.append(f"定位:{c.role_type}")
    if c.persona:
        parts.append(f"性格:{c.persona}")
    parts.append("电影级肖像,半身构图,自然光,高细节,写实风格")
    return "。".join(parts)


def _portrait_view(media: Media, token: str, exp: int) -> dict[str, Any]:
    """构造 `MediaPublic` 视图(media 元数据 + 短期签名 URL)。"""
    return {
        "media_id": media.id,
        "signed_url": build_signed_url(media.id, token, exp),
        "content_type": media.content_type,
        "width": media.width,
        "height": media.height,
        "source": media.source,
        "created_at": media.created_at,
    }
