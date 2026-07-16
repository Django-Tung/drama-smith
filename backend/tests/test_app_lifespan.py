"""lifespan 启动期执行器接线与启动恢复验证(tasks.md §9.4)。

直接以 `async with lifespan(app)` 触发启动 / 关闭(不经 TestClient)——与全 suite 共享
session 级事件循环(`asyncio_default_test_loop_scope=session`),故执行器与引擎落在同一 loop,
避免跨 loop 绑定(这也正是 `conftest.client` 标注「不触发 lifespan」的原因)。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from drama_smith.db.base import get_session_factory
from drama_smith.db.repositories import task_repo, user_repo
from drama_smith.main import create_app, lifespan
from drama_smith.storage import LocalFileStore
from drama_smith.tasks import TaskExecutor


async def test_lifespan_injects_executor_and_recovers_running(
    db_session: AsyncSession,
) -> None:
    """启动期:构造执行器注入 `app.state` + `recover_running` 把残留 running 标 interrupted。"""
    uid = (await user_repo.create(db_session, username="alice", password_hash="h")).id
    # 模拟上次进程未优雅退出:留一条 running 任务(episode_id 可空,无需剧集)
    task = await task_repo.create(db_session, uid, episode_id=None, type="analyze")
    await task_repo.start(db_session, uid, task.id)
    await db_session.commit()

    app = create_app()
    async with lifespan(app):
        # 启动期已构造并注入执行器
        assert isinstance(app.state.executor, TaskExecutor)
        # 启动期已构造并注入 FileStore(本地磁盘 + ensure_root,M3)
        assert isinstance(app.state.file_store, LocalFileStore)
        # recover_running 已跑过 → 该任务落 interrupted(经执行器自己的事务提交,
        # 故用全新 session 读,避开 db_session 的过期快照)
        async with get_session_factory()() as s:
            recovered = await task_repo.get(s, uid, task.id)
            assert recovered is not None
            assert recovered.status == "interrupted"
    # 退出 with:executor.shutdown() 收口(无异常即通过)
