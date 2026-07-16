"""剧集角色端点:`/api/episodes/:id/characters`(preset CRUD)。

接口层只解析参数 + 组装响应;用例编排、事务边界、归属校验在 `character_service`(薄包装
`episode_character_repo`)。preset 角色可经 API 增删改;分析产角色(`source='analysis'`)
只读(由拆解落库,不可经此改)。嵌套资源 `:cid` 须属 `:id`(否则 404 不泄露存在)。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Response, UploadFile, status

from drama_smith.api.deps import ExecutorDep, FileStoreDep, MekDep, SessionDep, UserDep
from drama_smith.api.schemas import (
    CharacterCreate,
    CharacterUpdate,
    Envelope,
    EpisodeCharacterPublic,
    ErrorResponse,
    MediaPublic,
    TaskPublic,
)
from drama_smith.core.config import get_settings
from drama_smith.services import character_media_service, character_service

router = APIRouter(prefix="/episodes", tags=["characters"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "剧集 / 角色不存在或越权访问(not_found)"}
}


@router.get(
    "/{episode_id}/characters",
    summary="列出剧集角色",
    response_model=Envelope[list[EpisodeCharacterPublic]],
    responses={**_NOT_FOUND},
)
async def list_characters(
    episode_id: int, user: UserDep, session: SessionDep
) -> Envelope[list[EpisodeCharacterPublic]]:
    chars = await character_service.list_characters(session, user.id, episode_id)
    return Envelope(data=[EpisodeCharacterPublic.model_validate(c) for c in chars])


@router.post(
    "/{episode_id}/characters",
    summary="新建预置角色",
    response_model=Envelope[EpisodeCharacterPublic],
    status_code=status.HTTP_201_CREATED,
    responses={**_NOT_FOUND},
)
async def create_character(
    episode_id: int, body: CharacterCreate, user: UserDep, session: SessionDep
) -> Envelope[EpisodeCharacterPublic]:
    char = await character_service.create_character(
        session,
        user.id,
        episode_id,
        name=body.name,
        role_type=body.role_type,
        persona=body.persona,
        motivation=body.motivation,
        traits=body.traits,
        appearance_desc=body.appearance_desc,
        sort_order=body.sort_order,
    )
    return Envelope(data=EpisodeCharacterPublic.model_validate(char))


@router.get(
    "/{episode_id}/characters/{character_id}",
    summary="获取角色",
    response_model=Envelope[EpisodeCharacterPublic],
    responses={**_NOT_FOUND},
)
async def get_character(
    episode_id: int, character_id: int, user: UserDep, session: SessionDep
) -> Envelope[EpisodeCharacterPublic]:
    char = await character_service.get_character(session, user.id, episode_id, character_id)
    return Envelope(data=EpisodeCharacterPublic.model_validate(char))


@router.put(
    "/{episode_id}/characters/{character_id}",
    summary="更新角色",
    description="仅转发显式给出的字段(白名单过滤);缺省不动、显式 null 清空可空字段。",
    response_model=Envelope[EpisodeCharacterPublic],
    responses={**_NOT_FOUND},
)
async def update_character(
    episode_id: int,
    character_id: int,
    body: CharacterUpdate,
    user: UserDep,
    session: SessionDep,
) -> Envelope[EpisodeCharacterPublic]:
    provided: dict[str, Any] = {k: getattr(body, k) for k in body.model_fields_set}
    char = await character_service.update_character(
        session, user.id, episode_id, character_id, fields=provided
    )
    return Envelope(data=EpisodeCharacterPublic.model_validate(char))


@router.delete(
    "/{episode_id}/characters/{character_id}",
    summary="删除角色",
    description="物理删;`shot_characters` FK CASCADE 清理出场引用。",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_NOT_FOUND},
)
async def delete_character(
    episode_id: int, character_id: int, user: UserDep, session: SessionDep
) -> None:
    await character_service.delete_character(session, user.id, episode_id, character_id)


# ---- 角色形象图(M3;upload 同步 / generate 异步 / get 读当前;design D5/D6/D8)----
# 端点拆 upload / generate(偏离 architecture §3.3 的「合一」为清晰分责,见 design D6)。
# get 无形象图 → 204(无 body);upload 201 + 签名 URL;generate 202 + 轮询 task。

_UPLOAD_ERR: dict[int | str, dict[str, Any]] = {
    413: {"model": ErrorResponse, "description": "上传超过硬上限(media_too_large)"},
    422: {
        "model": ErrorResponse,
        "description": "上传内容非图片 / 不支持格式(media_invalid)",
    },
}
_GENERATE_ERR: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorResponse,
        "description": (
            "无 active 图片配置(model_not_configured)/ 角色未填外形描述(invalid_state)"
        ),
    },
}


@router.get(
    "/{episode_id}/characters/{character_id}/portrait",
    summary="读取角色当前形象图",
    description="取角色当前选用形象图 + 短期签名 URL(`<img src>` 直用);无形象图 → 204。",
    response_model=Envelope[MediaPublic],
    responses={
        204: {"description": "该角色尚无形象图"},
        **_NOT_FOUND,
    },
)
async def get_character_portrait(
    episode_id: int,
    character_id: int,
    user: UserDep,
    session: SessionDep,
    file_store: FileStoreDep,
) -> Envelope[MediaPublic] | Response:
    view = await character_media_service.get_portrait(
        session, user.id, episode_id, character_id, file_store=file_store
    )
    if view is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return Envelope(data=MediaPublic.model_validate(view))


@router.post(
    "/{episode_id}/characters/{character_id}/portrait/upload",
    summary="上传角色形象图",
    description=(
        "multipart 上传图片(jpg/png/webp);Pillow 校验 + 超 1 MiB 递降 JPEG 压缩,"
        "同步落库返签名 URL。硬上限见 `DS_MEDIA_UPLOAD_MAX_BYTES`(默认 10 MiB)。"
    ),
    response_model=Envelope[MediaPublic],
    status_code=status.HTTP_201_CREATED,
    responses={**_NOT_FOUND, **_UPLOAD_ERR},
)
async def upload_character_portrait(
    episode_id: int,
    character_id: int,
    user: UserDep,
    session: SessionDep,
    file_store: FileStoreDep,
    file: Annotated[UploadFile, File(description="图片文件(jpg/png/webp)")],
) -> Envelope[MediaPublic]:
    data = await file.read()
    settings = get_settings()
    view = await character_media_service.upload_portrait(
        session,
        user.id,
        episode_id,
        character_id,
        file_store=file_store,
        data=data,
        max_bytes=settings.media_upload_max_bytes,
    )
    return Envelope(data=MediaPublic.model_validate(view))


@router.post(
    "/{episode_id}/characters/{character_id}/portrait/generate",
    summary="AI 生成角色形象图",
    description=(
        "门禁(active 图片配置 + 角色已填 `appearance_desc`)→ 异步生成(202 + 轮询 task)。"
        "成功 task `output_refs.media_id` 指向新生成的形象图。"
    ),
    response_model=Envelope[TaskPublic],
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_GENERATE_ERR},
)
async def generate_character_portrait(
    episode_id: int,
    character_id: int,
    user: UserDep,
    session: SessionDep,
    mek: MekDep,
    file_store: FileStoreDep,
    executor: ExecutorDep,
) -> Envelope[TaskPublic]:
    task = await character_media_service.generate_portrait(
        session,
        user.id,
        episode_id,
        character_id,
        mek=mek,
        file_store=file_store,
        executor=executor,
    )
    return Envelope(data=TaskPublic.model_validate(task))
