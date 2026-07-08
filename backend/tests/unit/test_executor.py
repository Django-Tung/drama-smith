"""任务执行器单测(D4):状态机、并发限流(排队)、协作式 cancel、异常落 failed、
启动恢复(running→interrupted)、优雅 shutdown(interrupted)。

executor **不耦合业务**:work 闭包在此用桩(真实调图 / 落产物见 service 集成测)。
执行器在后台 asyncio task 用独立 session 写 task 记录,故建 user/task 后必须 commit;
refetch 另开 session 读,避开请求 session 的 identity map 缓存。
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drama_smith.core.errors import AnalysisParseError, InvalidState
from drama_smith.db.base import get_session_factory
from drama_smith.db.repositories import task_repo, user_repo
from drama_smith.tasks import (
    CANCELED,
    FAILED,
    INTERRUPTED,
    PENDING,
    RUNNING,
    SUCCEEDED,
    TaskExecutor,
    assert_transition,
    can_transition,
)

_Factory = async_sessionmaker[AsyncSession]


async def _make_user(session: AsyncSession, username: str = "exe") -> int:
    return (await user_repo.create(session, username=username, password_hash="hash")).id


async def _refetch(factory: _Factory, user_id: int, task_id: int):
    async with factory() as session:
        return await task_repo.get(session, user_id, task_id)


async def _analyze_task(session: AsyncSession, user_id: int, **kwargs):
    return await task_repo.create(session, user_id, episode_id=None, type="analyze", **kwargs)


class TestStateMachine:
    def test_legal_transitions(self) -> None:
        assert can_transition(PENDING, RUNNING)
        assert can_transition(PENDING, CANCELED)
        assert can_transition(RUNNING, SUCCEEDED)
        assert can_transition(RUNNING, FAILED)
        assert can_transition(RUNNING, CANCELED)
        assert can_transition(RUNNING, INTERRUPTED)

    def test_terminal_states_are_dead_ends(self) -> None:
        for terminal in (SUCCEEDED, FAILED, CANCELED, INTERRUPTED):
            assert not can_transition(terminal, RUNNING)
            assert not can_transition(terminal, PENDING)

    def test_cannot_skip_running(self) -> None:
        assert not can_transition(PENDING, SUCCEEDED)
        assert not can_transition(PENDING, FAILED)

    def test_assert_transition_raises(self) -> None:
        with pytest.raises(InvalidState):
            assert_transition(SUCCEEDED, RUNNING)


class TestExecutor:
    async def test_submit_succeeds_writes_progress_and_output(self, db_session) -> None:
        factory = get_session_factory()
        executor = TaskExecutor(factory, max_per_user=2, max_global=4)
        uid = await _make_user(db_session)
        task = await _analyze_task(db_session, uid, input_snapshot={"k": "v"})
        await db_session.commit()

        ran: list[str] = []

        async def work(cb):
            await cb(50, "mid")
            ran.append("ran")
            return {"analysis_id": 9}

        atask = await executor.submit(task.id, uid, work)
        await atask

        row = await _refetch(factory, uid, task.id)
        assert row.status == SUCCEEDED
        assert row.progress == 50
        assert row.stage == "mid"
        assert row.output_refs == {"analysis_id": 9}
        assert row.started_at is not None and row.finished_at is not None
        assert ran == ["ran"]

    async def test_per_user_limit_queues_second_task(self, db_session) -> None:
        factory = get_session_factory()
        executor = TaskExecutor(factory, max_per_user=1, max_global=4)
        uid = await _make_user(db_session)
        t1 = await _analyze_task(db_session, uid)
        t2 = await _analyze_task(db_session, uid)
        await db_session.commit()

        gate = asyncio.Event()

        async def hold(cb):
            gate.set()
            await asyncio.sleep(0.05)

        async def queued_work(cb):
            await cb(10, "go")
            return {"ok": True}

        a1 = await executor.submit(t1.id, uid, hold)
        await gate.wait()  # t1 持有该用户唯一槽位
        a2 = await executor.submit(t2.id, uid, queued_work)

        # t2 在用户信号量上排队,未进 running
        row2 = await _refetch(factory, uid, t2.id)
        assert row2.status == PENDING

        await a1
        await a2
        assert (await _refetch(factory, uid, t2.id)).status == SUCCEEDED

    async def test_cancel_running_marks_canceled(self, db_session) -> None:
        factory = get_session_factory()
        executor = TaskExecutor(factory, max_per_user=2, max_global=4)
        uid = await _make_user(db_session)
        task = await _analyze_task(db_session, uid)
        await db_session.commit()

        started = asyncio.Event()

        async def long_work(cb):
            started.set()
            await asyncio.sleep(30)

        atask = await executor.submit(task.id, uid, long_work)
        await started.wait()
        assert await executor.cancel(task.id) is True
        await atask

        assert (await _refetch(factory, uid, task.id)).status == CANCELED

    async def test_cancel_unknown_task_is_noop(self) -> None:
        executor = TaskExecutor(get_session_factory(), max_per_user=2, max_global=4)
        assert await executor.cancel(999999) is False

    async def test_domain_error_marks_failed_with_code(self, db_session) -> None:
        factory = get_session_factory()
        executor = TaskExecutor(factory, max_per_user=2, max_global=4)
        uid = await _make_user(db_session)
        task = await _analyze_task(db_session, uid)
        await db_session.commit()

        async def bad(cb):
            raise AnalysisParseError("model returned garbage")

        atask = await executor.submit(task.id, uid, bad)
        await atask

        row = await _refetch(factory, uid, task.id)
        assert row.status == FAILED
        assert row.error["code"] == "analysis_parse_error"

    async def test_generic_error_maps_to_internal_error(self, db_session) -> None:
        factory = get_session_factory()
        executor = TaskExecutor(factory, max_per_user=2, max_global=4)
        uid = await _make_user(db_session)
        task = await _analyze_task(db_session, uid)
        await db_session.commit()

        async def bad(cb):
            raise RuntimeError("boom")

        atask = await executor.submit(task.id, uid, bad)
        await atask

        row = await _refetch(factory, uid, task.id)
        assert row.status == FAILED
        assert row.error["code"] == "internal_error"

    async def test_recover_running_interrupts(self, db_session) -> None:
        factory = get_session_factory()
        executor = TaskExecutor(factory, max_per_user=2, max_global=4)
        uid = await _make_user(db_session)
        task = await _analyze_task(db_session, uid)
        await db_session.commit()
        # 模拟重启前残留:直接置 running(不经 executor)
        await task_repo.start(db_session, uid, task.id)
        await db_session.commit()

        count = await executor.recover_running()
        assert count >= 1

        assert (await _refetch(factory, uid, task.id)).status == INTERRUPTED

    async def test_shutdown_interrupts_inflight(self, db_session) -> None:
        factory = get_session_factory()
        executor = TaskExecutor(factory, max_per_user=2, max_global=4)
        uid = await _make_user(db_session)
        task = await _analyze_task(db_session, uid)
        await db_session.commit()

        started = asyncio.Event()

        async def long_work(cb):
            started.set()
            await asyncio.sleep(30)

        await executor.submit(task.id, uid, long_work)
        await started.wait()
        await executor.shutdown()

        assert (await _refetch(factory, uid, task.id)).status == INTERRUPTED
