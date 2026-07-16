"""富媒体内容端点:`GET /api/media/{media_id}/content`(签名 URL 直读,免 Authorization)。

`<img src>` 直用签名 URL(D10):鉴权凭证是查询参数里的 token(`FileStore.verify` 校验
`sub == media_id` + 未过期),**不**走 Bearer。token 校验通过后按 `media_id` 取行读字节
(`storage_key`)→ `Response(content, media_type)` 流式下发。

非用户会话鉴权:故 `media_repo.get_by_id` 不按 `user_id` 过滤(凭证即授权);其余路径仍走
带 `user_id` 的 `media_repo.get`。
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from drama_smith.api.deps import FileStoreDep, SessionDep
from drama_smith.core.errors import NotFound, Unauthenticated
from drama_smith.db.repositories import media_repo

router = APIRouter(tags=["media"])


@router.get(
    "/media/{media_id}/content",
    summary="读取媒体字节(签名 URL)",
    description=(
        "经签名 URL 直读图片字节,免 Authorization。token = HS256(`{sub: media_id, exp}`, "
        "`jwt_secret`),`FileStore.verify` 校验 `sub == media_id` 且未过期。供 `<img src>` 直用。"
    ),
    responses={
        401: {"description": "token 无效 / 过期 / media_id 不符(unauthenticated)"},
        404: {"description": "media 不存在(not_found)"},
    },
)
async def get_media_content(
    media_id: int,
    token: str,
    exp: int,
    session: SessionDep,
    file_store: FileStoreDep,
) -> Response:
    # 校验签名凭证:`sub` 须等于路径 media_id 且未过期。`exp` 查询参仅前端预判用,以 token 内嵌为准。
    if not file_store.verify(token, media_id):
        raise Unauthenticated("Invalid or expired media token")
    media = await media_repo.get_by_id(session, media_id)
    if media is None:
        raise NotFound("Media not found")
    data = file_store.read(media.storage_key)
    return Response(
        content=data,
        media_type=media.content_type or "application/octet-stream",
        status_code=status.HTTP_200_OK,
        headers={"Cache-Control": "private, max-age=60"},
    )
