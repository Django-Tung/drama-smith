"""FastAPI 应用入口。

挂载 `/api` 前缀的 REST 路由(后续补 `/ws/tasks`),配置 CORS,
并在 lifespan 中完成启动初始化。DB 引擎、任务执行器与启动恢复
在后续任务组接入(见 `docs/tech-solution/backend.md` §3)。
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from drama_smith.api.health import router as health_router
from drama_smith.core.config import get_settings

logger = logging.getLogger("drama_smith")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    logger.info("drama-smith 启动 environment=%s", settings.environment)
    # TODO(后续任务组):初始化 async 引擎、任务执行器、启动恢复。
    yield
    logger.info("drama-smith 关闭")


def create_app() -> FastAPI:
    """构造 FastAPI 应用(供 uvicorn 导入与测试复用)。"""
    settings = get_settings()
    app: FastAPI = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix="/api")
    return app


app = create_app()
