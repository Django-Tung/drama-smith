import { useCallback, useEffect, useRef, useState } from 'react'

import { tasksApi } from '@/api/endpoints'
import { TASK_TERMINAL } from '@/types'
import type { Task } from '@/types'

/** 退避档位(design Open Questions 基线):pending 低频、running 高频、stage 切换瞬间最快。 */
const DELAY_PENDING = 5000
const DELAY_RUNNING = 3000
const DELAY_STAGE_CHANGE = 2000

export interface UseTaskPollingOptions {
  /** 命中终态(succeeded/failed/canceled/interrupted)时回调一次。 */
  onTerminal?: (task: Task) => void
}

export interface UseTaskPollingResult {
  /** 最新任务快照(含 progress / stage / status)。 */
  task: Task | null
  /** 协作式取消(`POST /tasks/:id/cancel`);终态任务 409 静默忽略。 */
  cancel: () => Promise<void>
}

/**
 * 单任务轮询(D10):`taskId` 非 null 即开始指数退避轮询 `GET /api/tasks/:id`,
 * 命中 `TASK_TERMINAL` 停止并触发 `onTerminal`。退避随状态 / stage 切换动态:
 * pending=5s、running=3s、stage 变化瞬间=2s。卸载或 `taskId` 变化时清 timer +
 * 以 `cancelled` 标志丢弃陈旧结果(请求本身极轻,不必 abort)。
 *
 * 工作台挂两个实例(analyze / optimize 各一),互不干扰。
 */
export function useTaskPolling(
  taskId: number | null,
  opts: UseTaskPollingOptions = {},
): UseTaskPollingResult {
  const { onTerminal } = opts
  const [task, setTask] = useState<Task | null>(null)
  const lastStageRef = useRef<string | null>(null)
  // onTerminal 入最新引用(避免它变化时重启 effect / 丢轮询)。
  const onTerminalRef = useRef(onTerminal)
  onTerminalRef.current = onTerminal

  useEffect(() => {
    if (taskId == null) {
      setTask(null)
      lastStageRef.current = null
      return
    }

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    /** 按上一档与本次 stage 计算下次退避;同时更新 lastStage。 */
    const delayFor = (t: Task): number => {
      const stageChanged = lastStageRef.current != null && t.stage !== lastStageRef.current
      lastStageRef.current = t.stage
      if (stageChanged) return DELAY_STAGE_CHANGE
      return t.status === 'pending' ? DELAY_PENDING : DELAY_RUNNING
    }

    const tick = async () => {
      if (cancelled) return
      let t: Task
      try {
        t = await tasksApi.get(taskId)
      } catch {
        // 网络 / 鉴权瞬态 → 稍后重试(不中断轮询)。
        if (!cancelled) timer = setTimeout(tick, DELAY_RUNNING)
        return
      }
      if (cancelled) return
      setTask(t)
      if (TASK_TERMINAL.includes(t.status)) {
        onTerminalRef.current?.(t)
        return // 终态:停轮询
      }
      timer = setTimeout(tick, delayFor(t))
    }

    void tick()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [taskId])

  const cancel = useCallback(async () => {
    if (taskId == null) return
    try {
      await tasksApi.cancel(taskId)
    } catch {
      // 终态任务 cancel → 409 invalid_state,静默忽略;轮询会自然停在终态。
    }
  }, [taskId])

  return { task, cancel }
}
