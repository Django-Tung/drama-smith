"""健康检查端点。"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """无鉴权探活端点,供部署健康检查与前端联调。

    挂载于 `/api` 前缀下,实际路径为 `GET /api/health`。
    """
    return {"status": "ok"}
