import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, ArrowLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { ApiError } from '@/api/errors'
import { analysisApi, episodesApi } from '@/api/endpoints'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import type { AnalysisSummary, Episode } from '@/types'
import { CastTab } from './CastTab'
import { ScriptTab } from './ScriptTab'

type Tab = 'script' | 'cast' | 'shots'

const TABS: { key: Tab; label: string }[] = [
  { key: 'script', label: '剧本与优化' },
  { key: 'cast', label: '角色与拆解' },
  { key: 'shots', label: '分镜编辑' },
]

function errMsg(e: unknown, fallback: string): string {
  return ApiError.isApiError(e) ? e.message : fallback
}

/**
 * 剧集工作台(§13.2–13.4 页级壳)。
 * 单路由 `/episodes/:episodeId` + 页内三 tab(剧本 / 角色 / 分镜);切 tab 不重取、
 * 不中断轮询。
 *
 * 页级共享态:`summary`(D11 双语义)+ analyze 轮询(跨刷新续跑 `summary.inflight_task`,
 * succeeded/失败均刷 summary)。`stale_flag` 真 → 全页顶部琥珀条(不阻断)。本批接入
 * 剧本 tab + 角色与拆解 tab;分镜 tab 占位(批 6 接 `<ShotsTab>`,读 `summary.current_analysis`)。
 *
 * 剧集不存在 / 越权(`GET /episodes/:id` 404)→ 回剧库。
 */
export function EpisodeWorkbench({ episodeId }: { episodeId: number }) {
  const navigate = useNavigate()
  const [episode, setEpisode] = useState<Episode | null>(null)
  const [summary, setSummary] = useState<AnalysisSummary | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('script')

  // analyze 轮询(跨 tab;影响 summary + 分镜)。
  const [analyzeTaskId, setAnalyzeTaskId] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      setStatus('loading')
      setError(null)
      try {
        const [ep, s] = await Promise.all([
          episodesApi.get(episodeId),
          analysisApi.getSummary(episodeId),
        ])
        if (cancelled) return
        setEpisode(ep)
        setSummary(s)
        // 续跑在途拆解(跨刷新)。
        setAnalyzeTaskId(s.inflight_task?.id ?? null)
        setStatus('ready')
      } catch (e) {
        if (cancelled) return
        if (ApiError.isApiError(e) && e.status === 404) {
          navigate('/dramas', { replace: true })
          return
        }
        setError(errMsg(e, '加载剧集失败'))
        setStatus('error')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [episodeId, navigate])

  const refreshSummary = useCallback(async () => {
    try {
      setSummary(await analysisApi.getSummary(episodeId))
    } catch {
      // summary 为体验态;刷新失败不阻断(下次轮询 / 操作会再拉)。
    }
  }, [episodeId])

  // analyze 终态:succeeded → summary 更新(current 移到新 analysis);失败也刷(清在途)。
  const onAnalyzeTerminal = useCallback(() => {
    setAnalyzeTaskId(null)
    void refreshSummary()
  }, [refreshSummary])

  const aPoll = useTaskPolling(analyzeTaskId, { onTerminal: onAnalyzeTerminal })

  const startAnalyze = useCallback(async () => {
    // 抛给 CastTab 自行展示错误(不污染页级 error 态)。
    const task = await analysisApi.analyze(episodeId)
    setAnalyzeTaskId(task.id)
  }, [episodeId])

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => navigate('/dramas')}
          aria-label="返回剧库"
        >
          <ArrowLeft />
        </Button>
        <div>
          <h2 className="text-lg font-semibold">{episode ? episode.title : '剧集'}</h2>
          {episode ? (
            <p className="text-xs text-muted-foreground">
              画幅 {episode.aspect_ratio}
              {episode.style_preset ? ` · ${episode.style_preset}` : ''}
            </p>
          ) : null}
        </div>
      </div>

      {/* stale 条幅(D11:剧本已改、当前分镜基于旧版;不阻断) */}
      {summary?.stale_flag ? (
        <div className="flex items-start gap-2 rounded-md border border-amber-300/60 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-500/40 dark:bg-amber-950/40 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>
            当前分镜基于旧版剧本。建议在「角色与拆解」重新发起拆解,或在历史分析中切回匹配版本。
          </span>
        </div>
      ) : null}

      {/* tab 栏(手写;shadcn 无 tabs 原语) */}
      <div className="flex gap-1 border-b">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              tab === t.key
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {status === 'loading' ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner /> 加载中…
        </p>
      ) : status === 'error' ? (
        <p className="text-sm font-medium text-destructive">{error}</p>
      ) : (
        <>
          {tab === 'script' ? <ScriptTab episodeId={episodeId} /> : null}
          {tab === 'cast' ? (
            <CastTab
              episodeId={episodeId}
              summary={summary}
              analyzeTask={aPoll.task}
              onStartAnalyze={startAnalyze}
              onCancelAnalyze={aPoll.cancel}
              onSummaryRefresh={refreshSummary}
            />
          ) : null}
          {tab === 'shots' ? (
            <p className="text-sm text-muted-foreground">分镜编辑(后续批次接入)。</p>
          ) : null}
        </>
      )}
    </div>
  )
}
