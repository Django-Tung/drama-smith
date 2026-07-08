"""进程内任务执行器(D4):状态机 + 并发限流 + 进度回调 + 启动恢复。

不耦合业务:service 注入 `work` 闭包,executor 只调度 + 写 task 记录。
"""

from __future__ import annotations

from drama_smith.tasks.executor import TaskExecutor, Work
from drama_smith.tasks.progress import ProgressCallback, make_progress_cb
from drama_smith.tasks.recover import recover_running
from drama_smith.tasks.states import (
    CANCELED,
    FAILED,
    INFLIGHT,
    INTERRUPTED,
    PENDING,
    RUNNING,
    SUCCEEDED,
    TERMINAL,
    assert_transition,
    can_transition,
)

__all__ = [
    "CANCELED",
    "FAILED",
    "INFLIGHT",
    "INTERRUPTED",
    "PENDING",
    "ProgressCallback",
    "RUNNING",
    "SUCCEEDED",
    "TERMINAL",
    "TaskExecutor",
    "Work",
    "assert_transition",
    "can_transition",
    "make_progress_cb",
    "recover_running",
]
