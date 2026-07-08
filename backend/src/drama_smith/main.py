"""FastAPI 应用入口。

挂载 `/api` 前缀的 REST 路由(后续补 `/ws/tasks`),配置 CORS,
并在 lifespan 中完成启动初始化:DB 引擎、任务执行器(构造 + `recover_running` 把残留
running → interrupted + 注入 `app.state.executor`),关闭期 `executor.shutdown()` 与引擎释放。
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from drama_smith.api.analysis import router as analysis_router
from drama_smith.api.auth import router as auth_router
from drama_smith.api.characters import router as characters_router
from drama_smith.api.dramas import router as dramas_router
from drama_smith.api.episodes import router as episodes_router
from drama_smith.api.health import router as health_router
from drama_smith.api.me import router as me_router
from drama_smith.api.models import router as models_router
from drama_smith.api.shots import router as shots_router
from drama_smith.api.tasks import router as tasks_router
from drama_smith.core.config import get_settings
from drama_smith.core.errors import register_exception_handlers
from drama_smith.db.base import dispose_engine, get_session_factory
from drama_smith.tasks import TaskExecutor

logger = logging.getLogger("drama_smith")

# Swagger 分组说明(与各路由 `tags` 名称对应)。
_OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "health", "description": "健康检查 / 探活(无鉴权)。"},
    {"name": "auth", "description": "用户注册、登录、登出与令牌刷新。"},
    {"name": "users", "description": "当前用户信息。"},
    {"name": "models", "description": "BYOK 模型配置(文本/图片/视频):CRUD、激活、零成本自检。"},
    {"name": "dramas", "description": "剧目(CRUD)与剧集子集合。"},
    {"name": "episodes", "description": "剧集 CRUD、剧本版本与 AI 优化(异步)。"},
    {"name": "characters", "description": "剧集预置角色 CRUD。"},
    {"name": "analysis", "description": "结构化拆解(异步)+ 双语义读 + 当前分析切换。"},
    {"name": "shots", "description": "分镜列表 / 重排 / 拆 / 合 / 改(含出场角色读写)。"},
    {"name": "tasks", "description": "任务读 + 协作式取消(异步用例轮询)。"},
]

_APP_DESCRIPTION = (
    "drama-smith 后端 API。\n\n"
    "**响应约定** — 成功:`{data, meta}`;错误:`{error: {code, message, details}}`。\n\n"
    "**鉴权** — 除 `register` / `login` / `refresh` 外,所有端点需在请求头携带"
    "`Authorization: Bearer <access_token>`。access 为 HS256 JWT(15min);"
    "refresh 为不透明可吊销令牌(7d)。"
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    logger.info("drama-smith 启动 environment=%s", settings.environment)
    # 任务执行器:进程内 asyncio,接 session_factory(顺带初始化异步引擎)。
    executor = TaskExecutor(
        get_session_factory(),
        settings.max_tasks_per_user,
        settings.max_global_workers,
    )
    recovered = await executor.recover_running()  # 残留 running → interrupted
    if recovered:
        logger.info("启动恢复:残留 running 任务 → interrupted,count=%s", recovered)
    app.state.executor = executor
    yield
    logger.info("drama-smith 关闭:停执行器 + 释放 DB 连接")
    await executor.shutdown()
    await dispose_engine()


def create_app() -> FastAPI:
    """构造 FastAPI 应用(供 uvicorn 导入与测试复用)。"""
    settings = get_settings()
    app: FastAPI = FastAPI(
        title=settings.app_name,
        description=_APP_DESCRIPTION,
        version="0.1.0",
        openapi_tags=_OPENAPI_TAGS,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 统一错误格式(`{error:{code,message,details}}`)覆盖 FastAPI 默认响应。
    register_exception_handlers(app)

    app.include_router(health_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(me_router, prefix="/api")
    app.include_router(models_router, prefix="/api")
    app.include_router(dramas_router, prefix="/api")
    app.include_router(episodes_router, prefix="/api")
    app.include_router(characters_router, prefix="/api")
    app.include_router(analysis_router, prefix="/api")
    app.include_router(shots_router, prefix="/api")
    app.include_router(tasks_router, prefix="/api")
    return app


app = create_app()
