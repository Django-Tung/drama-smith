import { useEffect, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { ApiError } from '@/api/errors'
import { episodesApi } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import type { Episode } from '@/types'
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
 * 不中断轮询。本批仅「剧本与优化」tab 落地;analyze 轮询 + summary + `<CastTab>`
 * 在批 5、`<ShotsTab>` 在批 6 接入(届时本壳增 summary 加载 + 在途任务续跑 + stale 条幅)。
 *
 * 剧集不存在 / 越权(`GET /episodes/:id` 404)→ 回剧库。
 */
export function EpisodeWorkbench({ episodeId }: { episodeId: number }) {
  const navigate = useNavigate()
  const [episode, setEpisode] = useState<Episode | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('script')

  useEffect(() => {
    let cancelled = false
    void (async () => {
      setStatus('loading')
      setError(null)
      try {
        const ep = await episodesApi.get(episodeId)
        if (cancelled) return
        setEpisode(ep)
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
            <p className="text-sm text-muted-foreground">角色与拆解(后续批次接入)。</p>
          ) : null}
          {tab === 'shots' ? (
            <p className="text-sm text-muted-foreground">分镜编辑(后续批次接入)。</p>
          ) : null}
        </>
      )}
    </div>
  )
}
