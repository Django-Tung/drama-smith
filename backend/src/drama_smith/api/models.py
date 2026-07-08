"""模型配置端点(BYOK):`/api/me/models/...`。

接口层只做参数解析与响应组装;用例编排、事务边界、加密、自检在
`services.model_config_service`。所有端点需鉴权,且经 service 强制 `user_id` 过滤
(越权访问他人配置 → 404,不泄露存在性)。明文 API Key 永不出现在请求(除创建/更新体)
与任何响应(只回脱敏串)。

各端点经 `summary` / `description` / `responses` 暴露给 Swagger;错误响应统一引用
`ErrorResponse`(`{error: {code, message, details}}`)。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from drama_smith.api.deps import MekDep, SessionDep, UserDep
from drama_smith.api.schemas import (
    Envelope,
    ErrorResponse,
    ModelConfigCreate,
    ModelConfigPublic,
    ModelConfigUpdate,
)
from drama_smith.services import model_config_service

router = APIRouter(prefix="/me/models", tags=["models"])

# 公共错误响应片段。
_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "配置不存在或越权访问(not_found)"}
}
_VALIDATION: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "请求体校验失败(validation_error)"}
}
_PROVIDER_ERR: dict[int | str, dict[str, Any]] = {
    502: {
        "model": ErrorResponse,
        "description": "供应商鉴权失败(provider_auth_failed)/ 限流(rate_limited)",
    }
}


def _public(cfg: Any) -> ModelConfigPublic:
    return ModelConfigPublic.model_validate(cfg)


@router.get(
    "",
    summary="列出我的模型配置",
    description="返回当前用户的模型配置(仅脱敏 key);`purpose` 可选过滤。",
    response_model=Envelope[list[ModelConfigPublic]],
)
async def list_configs(
    user: UserDep,
    session: SessionDep,
    purpose: Annotated[str | None, Query(description="按用途过滤:text / image / video")] = None,
) -> Envelope[list[ModelConfigPublic]]:
    configs = await model_config_service.list_configs(session, user.id, purpose)
    return Envelope(data=[_public(c) for c in configs])


@router.get(
    "/{config_id}",
    summary="获取单条模型配置",
    response_model=Envelope[ModelConfigPublic],
    responses={**_NOT_FOUND},
)
async def get_config(
    config_id: int, user: UserDep, session: SessionDep
) -> Envelope[ModelConfigPublic]:
    cfg = await model_config_service.get_config(session, user.id, config_id)
    return Envelope(data=_public(cfg))


@router.post(
    "",
    summary="新建模型配置",
    description=(
        "白名单校验 → 信封加密落库 → 首条自动 active。明文 api_key 仅本次加密,"
        "响应只回脱敏串。冲突(如 active 唯一竞态)→ 409。"
    ),
    response_model=Envelope[ModelConfigPublic],
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse, "description": "active 唯一冲突(conflict)"},
        **_VALIDATION,
    },
)
async def create_config(
    body: ModelConfigCreate, user: UserDep, session: SessionDep, mek: MekDep
) -> Envelope[ModelConfigPublic]:
    cfg = await model_config_service.create_config(
        session,
        user.id,
        purpose=body.purpose,
        provider=body.provider,
        model=body.model,
        api_key=body.api_key,
        mek=mek,
        base_url=body.base_url,
        params=body.params,
        provider_options=body.provider_options,
    )
    return Envelope(data=_public(cfg))


@router.put(
    "/{config_id}",
    summary="更新模型配置",
    description=(
        "按字段更新;`api_key` 缺省 / null → 不动加密列(D8),给出则全量重封。"
        "`purpose` 不可改。删 active 语义见 DELETE。"
    ),
    response_model=Envelope[ModelConfigPublic],
    responses={
        **_NOT_FOUND,
        409: {"model": ErrorResponse, "description": "active 唯一冲突(conflict)"},
        **_VALIDATION,
    },
)
async def update_config(
    config_id: int,
    body: ModelConfigUpdate,
    user: UserDep,
    session: SessionDep,
    mek: MekDep,
) -> Envelope[ModelConfigPublic]:
    # 仅传显式给出的字段(model_fields_set);缺省字段保持 _UNSET(不动),null 可清空 base_url。
    provided: dict[str, Any] = {}
    fields = body.model_fields_set
    if "provider" in fields:
        provided["provider"] = body.provider
    if "model" in fields:
        provided["model"] = body.model
    if "base_url" in fields:
        provided["base_url"] = body.base_url
    if "params" in fields:
        provided["params"] = body.params
    if "provider_options" in fields:
        provided["provider_options"] = body.provider_options
    if "api_key" in fields and body.api_key is not None:
        provided["api_key"] = body.api_key
    updated = await model_config_service.update_config(
        session, user.id, config_id, mek=mek, **provided
    )
    return Envelope(data=_public(updated))


@router.delete(
    "/{config_id}",
    summary="删除模型配置",
    description=(
        "删 active 且同 purpose 仍有兄弟 → 须显式 `new_active_id`(否则 409 invalid_state),"
        "继任被提升为 active。删后 0 条:text 回未配态,image/video 仅禁用。"
    ),
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        **_NOT_FOUND,
        409: {"model": ErrorResponse, "description": "删 active 须指定继任(invalid_state)"},
    },
)
async def delete_config(
    config_id: int,
    user: UserDep,
    session: SessionDep,
    new_active_id: Annotated[int | None, Query(description="删 active 时的继任配置 id")] = None,
) -> None:
    await model_config_service.delete_config(
        session, user.id, config_id, new_active_id=new_active_id
    )


@router.post(
    "/{config_id}/activate",
    summary="激活模型配置",
    description="单事务内置指定配置为当前 purpose 的 active(其余翻 0,D3)。",
    response_model=Envelope[ModelConfigPublic],
    responses={**_NOT_FOUND},
)
async def activate_config(
    config_id: int, user: UserDep, session: SessionDep
) -> Envelope[ModelConfigPublic]:
    cfg = await model_config_service.activate_config(session, user.id, config_id)
    return Envelope(data=_public(cfg))


@router.post(
    "/{config_id}/test",
    summary="零成本自检",
    description=(
        "解密 Key → 探测供应商 `GET /models`(不真生成)→ 回写 `last_tested_at`。"
        "鉴权失败(401/403)置 `status=invalid` + 502;限流 / 超时 → 502(不置 invalid)。"
    ),
    response_model=Envelope[ModelConfigPublic],
    responses={**_NOT_FOUND, **_PROVIDER_ERR},
)
async def test_config(
    config_id: int, user: UserDep, session: SessionDep, mek: MekDep
) -> Envelope[ModelConfigPublic]:
    cfg = await model_config_service.test_config(session, user.id, config_id, mek=mek)
    return Envelope(data=_public(cfg))
