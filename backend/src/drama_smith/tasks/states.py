"""任务状态机(承接 [`backend.md §7.2`](../../tech-solution/backend.md))。

合法流转::

    pending → running | canceled        # 排队中可直接取消
    running → succeeded | failed | canceled | interrupted
    终态(succeeded / failed / canceled / interrupted)不可再流转

`interrupted` 仅由启动恢复 / 优雅 shutdown 落(进程重启或停机),正常路径不产生。
"""

from __future__ import annotations

from drama_smith.core.errors import InvalidState

PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELED = "canceled"
INTERRUPTED = "interrupted"

TERMINAL = frozenset({SUCCEEDED, FAILED, CANCELED, INTERRUPTED})
INFLIGHT = frozenset({PENDING, RUNNING})

_TRANSITIONS: dict[str, frozenset[str]] = {
    PENDING: frozenset({RUNNING, CANCELED}),
    RUNNING: frozenset({SUCCEEDED, FAILED, CANCELED, INTERRUPTED}),
}


def can_transition(from_status: str, to_status: str) -> bool:
    """`from → to` 是否合法流转;终态出发一律 False。"""
    return to_status in _TRANSITIONS.get(from_status, frozenset())


def assert_transition(from_status: str, to_status: str) -> None:
    """非法流转 → `InvalidState`(供 service / API 层门禁)。"""
    if not can_transition(from_status, to_status):
        raise InvalidState(
            f"Task cannot transition from {from_status!r} to {to_status!r}",
            details={"from": from_status, "to": to_status},
        )


__all__ = [
    "CANCELED",
    "FAILED",
    "INFLIGHT",
    "INTERRUPTED",
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "TERMINAL",
    "assert_transition",
    "can_transition",
]
