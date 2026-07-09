import { useCallback, useEffect, useState } from 'react'
import { Check, Sparkles, X } from 'lucide-react'

import { ApiError } from '@/api/errors'
import { episodesApi } from '@/api/endpoints'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import { Field } from '@/components/Field'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'
import { formatDateTime } from '@/utils/format'
import type { ScriptFormat, ScriptVersion, Task } from '@/types'
import { narrowOptimizeRefs, type OptimizeResult } from './optimize'
import { DiffView } from './DiffView'

/** 原生 select 样式,贴近 Input(无 shadcn select 原语);与 DramasPage 同款。 */
const SELECT_CLS =
  'h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50'

const FORMATS: { value: ScriptFormat; label: string }[] = [
  { value: 'plain', label: '纯文本' },
  { value: 'markdown', label: 'Markdown' },
  { value: 'fountain', label: 'Fountain' },
]

function errMsg(e: unknown, fallback: string): string {
  return ApiError.isApiError(e) ? e.message : fallback
}

/** 从 `Task.error`({ code, message })取失败文案;字段缺失用 fallback。 */
function taskFailMessage(t: Task, fallback: string): string {
  const m = t.error?.['message']
  return typeof m === 'string' ? m : fallback
}

/**
 * 在途 optimize 任务的 sessionStorage 持久化(按剧集)。
 *
 * ScriptTab 随 tab 切换 / 路由离开而 unmount,本地 `optimizeTaskId` 与 `optimizeResult`
 * 会丢失。analyze 轮询能跨刷新续跑是因为后端 `summary.inflight_task` 回报了在途任务;
 * optimize 无此汇总端点,故把任务 id 落 sessionStorage:mounnt 时读回 → 重启轮询。
 * 因 diff 存于任务的 `output_refs`,恢复轮询即可重建进度(运行中)或整版 diff(已成功)。
 * sessionStorage 随标签关闭失效,匹配「在途任务」的时效(避免跨重启复活已被回收的任务)。
 */
const optimizeTaskStorageKey = (episodeId: number) => `ds-optimize-task:${episodeId}`

function readStoredOptimizeTaskId(episodeId: number): number | null {
  const raw = sessionStorage.getItem(optimizeTaskStorageKey(episodeId))
  if (!raw) return null
  const id = Number(raw)
  if (!Number.isInteger(id) || id <= 0) {
    sessionStorage.removeItem(optimizeTaskStorageKey(episodeId))
    return null
  }
  return id
}

function storeOptimizeTaskId(episodeId: number, taskId: number): void {
  sessionStorage.setItem(optimizeTaskStorageKey(episodeId), String(taskId))
}

function clearStoredOptimizeTaskId(episodeId: number): void {
  sessionStorage.removeItem(optimizeTaskStorageKey(episodeId))
}

/**
 * 剧本与优化 tab(§13.2)。
 * - 写入剧本:`upsertScript`(整版覆盖、产 `source='input'` 新版本、移 current 指针)。
 * - 版本列表(append-only):标 current;`selectVersion` 切换 / 回退到任一历史版本。
 * - AI 优化(D12):`optimize` 异步 202 → 自带 `useTaskPolling` 轮询;succeeded 收敛
 *   `output_refs` 为 `{version_id, diff}` 驱动只读 `<DiffView>`;整版「接受」(select)/
 *   「拒绝」(reject、版本保留、指针不动)。**无段落勾选 / 部分采纳**。在途任务 id 落
 *   sessionStorage,mount 时读回复跑轮询 → 切 tab / 离开路由 / 刷新不丢进度与 diff。
 *
 * 无 script 容器(getScript 404)→ 空状态;optimize 门禁:无当前版本时禁用。
 */
export function ScriptTab({ episodeId }: { episodeId: number }) {
  const [versions, setVersions] = useState<ScriptVersion[]>([])
  const [currentVersionId, setCurrentVersionId] = useState<number | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)

  const [content, setContent] = useState('')
  const [format, setFormat] = useState<ScriptFormat>('markdown')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const [optimizeTaskId, setOptimizeTaskId] = useState<number | null>(null)
  const [optimizeResult, setOptimizeResult] = useState<OptimizeResult | null>(null)
  const [optimizeError, setOptimizeError] = useState<string | null>(null)
  const [busyVersion, setBusyVersion] = useState<number | null>(null)

  const load = useCallback(async () => {
    setStatus('loading')
    setError(null)
    try {
      // 先取 script 容器(无容器 → 404);有则再列版本(新→旧)。
      const script = await episodesApi.getScript(episodeId)
      const vers = await episodesApi.listScriptVersions(episodeId)
      setCurrentVersionId(script.current_version_id)
      setVersions(vers)
      setStatus('ready')
    } catch (e) {
      if (ApiError.isApiError(e) && e.status === 404) {
        // 尚未写过剧本:无 script 容器 → 空状态。
        setCurrentVersionId(null)
        setVersions([])
        setStatus('ready')
      } else {
        setError(errMsg(e, '加载剧本失败'))
        setStatus('error')
      }
    }
  }, [episodeId])

  useEffect(() => {
    void load()
  }, [load])

  // 续跑在途 optimize(跨切 tab / 导航 / 刷新):读回任务 id → 重启轮询(进度或重建 diff)。
  useEffect(() => {
    const stored = readStoredOptimizeTaskId(episodeId)
    if (stored != null) setOptimizeTaskId(stored)
  }, [episodeId])

  // optimize 轮询(self-contained;工作台另挂 analyze 轮询,两实例互不干扰)。
  // 终态时清 optimizeTaskId 停轮询;succeeded 保留 storage(diff 可跨导航经恢复轮询重建,
  // 直到 accept/reject),失败 / 无 diff 清 storage(无可恢复产物)。
  const onOptimizeTerminal = useCallback(
    (t: Task) => {
      setOptimizeTaskId(null)
      if (t.status === 'succeeded') {
        const r = narrowOptimizeRefs(t.output_refs)
        if (r) {
          setOptimizeResult(r)
          setOptimizeError(null)
        } else {
          setOptimizeResult(null)
          setOptimizeError('优化完成但未返回差异,请重试')
          clearStoredOptimizeTaskId(episodeId)
        }
      } else {
        setOptimizeResult(null)
        setOptimizeError(taskFailMessage(t, '优化失败'))
        clearStoredOptimizeTaskId(episodeId)
      }
    },
    [episodeId],
  )
  const oPoll = useTaskPolling(optimizeTaskId, { onTerminal: onOptimizeTerminal })

  const saveScript = useCallback(async () => {
    const c = content.trim()
    if (!c) {
      setSaveError('请输入剧本内容')
      return
    }
    setSaving(true)
    setSaveError(null)
    try {
      await episodesApi.upsertScript(episodeId, { content: c, format })
      setContent('')
      await load()
    } catch (e) {
      setSaveError(errMsg(e, '保存剧本失败'))
    } finally {
      setSaving(false)
    }
  }, [content, episodeId, format, load])

  const startOptimize = useCallback(async () => {
    setOptimizeError(null)
    setOptimizeResult(null)
    try {
      const task = await episodesApi.optimize(episodeId)
      storeOptimizeTaskId(episodeId, task.id)
      setOptimizeTaskId(task.id)
    } catch (e) {
      setOptimizeError(errMsg(e, '发起优化失败'))
    }
  }, [episodeId])

  const acceptOptimize = useCallback(
    async (versionId: number) => {
      setBusyVersion(versionId)
      try {
        await episodesApi.selectVersion(episodeId, versionId)
        setOptimizeResult(null)
        clearStoredOptimizeTaskId(episodeId)
        await load()
      } catch (e) {
        setOptimizeError(errMsg(e, '采纳失败'))
      } finally {
        setBusyVersion(null)
      }
    },
    [episodeId, load],
  )

  const rejectOptimize = useCallback(
    async (versionId: number) => {
      setBusyVersion(versionId)
      try {
        await episodesApi.rejectVersion(episodeId, versionId)
        setOptimizeResult(null)
        clearStoredOptimizeTaskId(episodeId)
      } catch (e) {
        setOptimizeError(errMsg(e, '拒绝失败'))
      } finally {
        setBusyVersion(null)
      }
    },
    [episodeId],
  )

  /** 列表行「切为此版本」= selectVersion(D6:accept=revert,移指针)。 */
  const pickVersion = useCallback(
    async (versionId: number) => {
      setBusyVersion(versionId)
      try {
        await episodesApi.selectVersion(episodeId, versionId)
        await load()
      } catch (e) {
        setError(errMsg(e, '切换版本失败'))
      } finally {
        setBusyVersion(null)
      }
    },
    [episodeId, load],
  )

  const hasScript = currentVersionId != null
  const optimizing = optimizeTaskId != null
  const canSave = content.trim().length > 0 && !saving

  return (
    <div className="space-y-6">
      {/* 写入剧本 */}
      <section className="space-y-3 rounded-lg border p-4">
        <Field label="剧本正文" htmlFor="script-content" error={saveError ?? undefined}>
          <Textarea
            id="script-content"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="粘贴或编写剧本正文(整版保存,产生新版本)…"
            className="min-h-48 font-serif"
            disabled={saving}
          />
        </Field>
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <label htmlFor="script-format" className="text-sm font-medium">
              格式
            </label>
            <select
              id="script-format"
              className={SELECT_CLS}
              value={format}
              onChange={(e) => setFormat(e.target.value as ScriptFormat)}
              disabled={saving}
            >
              {FORMATS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>
          <Button onClick={saveScript} disabled={!canSave}>
            {saving ? <Spinner className="mr-2" /> : <Check className="mr-2 size-4" />}
            保存为新版本
          </Button>
        </div>
      </section>

      {/* AI 优化(D12:整版接受 / 拒绝,只读 diff) */}
      <section className="space-y-3 rounded-lg border p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="font-medium">AI 优化(copy-edit)</h4>
          <Button
            variant="secondary"
            onClick={() => void startOptimize()}
            disabled={!hasScript || optimizing}
          >
            <Sparkles className="mr-2 size-4" />
            {optimizing ? '优化中…' : '润色当前剧本'}
          </Button>
        </div>
        {!hasScript ? (
          <p className="text-sm text-muted-foreground">先写入剧本,再发起优化。</p>
        ) : null}
        {optimizing && oPoll.task ? (
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <Spinner />
            <span>
              {oPoll.task.stage ?? '处理中'}
              {oPoll.task.progress > 0 ? ` · ${oPoll.task.progress}%` : ''}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void oPoll.cancel()}
              className="ml-auto"
            >
              取消
            </Button>
          </div>
        ) : null}
        {optimizeError ? (
          <p className="text-sm font-medium text-destructive">{optimizeError}</p>
        ) : null}
        {optimizeResult ? (
          <div className="space-y-3">
            <DiffView diff={optimizeResult.diff} />
            <div className="flex gap-2">
              <Button
                onClick={() => void acceptOptimize(optimizeResult.version_id)}
                disabled={busyVersion != null}
              >
                {busyVersion === optimizeResult.version_id ? (
                  <Spinner className="mr-2" />
                ) : (
                  <Check className="mr-2 size-4" />
                )}
                整版接受(移指针)
              </Button>
              <Button
                variant="outline"
                onClick={() => void rejectOptimize(optimizeResult.version_id)}
                disabled={busyVersion != null}
              >
                <X className="mr-2 size-4" />
                拒绝(保留版本)
              </Button>
            </div>
          </div>
        ) : null}
      </section>

      {/* 版本列表(append-only;标 current;可切换 / 回退) */}
      <section className="space-y-3">
        <h4 className="font-medium">剧本版本</h4>
        {status === 'loading' ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : status === 'error' ? (
          <p className="text-sm font-medium text-destructive">{error}</p>
        ) : versions.length === 0 ? (
          <p className="text-sm text-muted-foreground">尚未写入剧本。</p>
        ) : (
          <ul className="space-y-2">
            {versions.map((v) => {
              const isCurrent = v.id === currentVersionId
              return (
                <li
                  key={v.id}
                  className={`space-y-1.5 rounded-md border p-3 text-sm ${
                    isCurrent ? 'border-primary/50 bg-primary/5' : ''
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono">v{v.version_no}</span>
                    <Badge variant={v.source === 'optimize' ? 'outline' : 'secondary'}>
                      {v.source === 'optimize' ? 'AI 优化' : '输入'}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {formatDateTime(v.created_at)}
                    </span>
                    {isCurrent ? (
                      <Badge className="ml-auto">当前</Badge>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="ml-auto"
                        onClick={() => void pickVersion(v.id)}
                        disabled={busyVersion != null}
                      >
                        {busyVersion === v.id ? <Spinner className="mr-1" /> : null}
                        切为此版本
                      </Button>
                    )}
                  </div>
                  <p className="line-clamp-3 whitespace-pre-wrap font-serif text-muted-foreground">
                    {v.content}
                  </p>
                </li>
              )
            })}
          </ul>
        )}
      </section>
    </div>
  )
}
