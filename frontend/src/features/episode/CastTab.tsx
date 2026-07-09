import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Pencil, Plus, Trash2, Wand2 } from 'lucide-react'

import { ApiError } from '@/api/errors'
import { analysisApi, charactersApi } from '@/api/endpoints'
import { useAuthStore } from '@/stores/auth'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Overlay } from '@/components/Overlay'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/utils/cn'
import { formatDateTime } from '@/utils/format'
import type {
  Analysis,
  AnalysisResult,
  AnalysisSummary,
  EpisodeCharacter,
  Task,
} from '@/types'
import { CharacterForm } from './CharacterForm'
import { splitTraits } from './schema'

/** 原生 select 样式,贴近 Input(无 shadcn select 原语);与 DramasPage / ScriptTab 同款。 */
const SELECT_CLS =
  'h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50'

/** 工作台注入:summary + analyze 轮询(页级共享)+ 发起 / 取消 / 刷新回调。 */
export interface CastTabProps {
  episodeId: number
  summary: AnalysisSummary | null
  analyzeTask: Task | null
  onStartAnalyze: () => Promise<void>
  onCancelAnalyze: () => Promise<void>
  onSummaryRefresh: () => Promise<void>
}

function errMsg(e: unknown, fallback: string): string {
  return ApiError.isApiError(e) ? e.message : fallback
}

type CharOverlay =
  | { mode: 'create' }
  | { mode: 'edit'; character: EpisodeCharacter }
  | null

/**
 * 角色与拆解 tab(§13.3)。
 * - 发起拆解:门禁 `text_model_configured`(假 → 禁用 + 去设置);真 →
 *   `onStartAnalyze`(工作台置 analyzeTaskId、页级轮询)。
 * - 轮询中:进度条(stage + progress%)+ 协作式取消。
 * - 四维结果(`summary.current_analysis.result`):只读摘要(索引兜底容忍)。
 * - 角色(D7 两源并列):preset 可增 / 改 / 删(`<Overlay>` + `CharacterForm`);
 *   analysis 只读 + 标注「由拆解产出」,无合并 UI。
 * - 历史切换(D11):`listHistory` >1 → `<select>` 选历史 → `selectCurrent` → 刷新 summary。
 */
export function CastTab({
  episodeId,
  summary,
  analyzeTask,
  onStartAnalyze,
  onCancelAnalyze,
  onSummaryRefresh,
}: CastTabProps) {
  const configured = useAuthStore((s) => s.user?.text_model_configured) ?? false
  const analyzing = analyzeTask != null

  const [characters, setCharacters] = useState<EpisodeCharacter[]>([])
  const [charsStatus, setCharsStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [charsError, setCharsError] = useState<string | null>(null)

  const [history, setHistory] = useState<Analysis[]>([])
  const [historyBusy, setHistoryBusy] = useState(false)
  const [switchError, setSwitchError] = useState<string | null>(null)

  const [charOverlay, setCharOverlay] = useState<CharOverlay>(null)
  const [confirmDelete, setConfirmDelete] = useState<EpisodeCharacter | null>(null)
  const [charBusy, setCharBusy] = useState<number | 'new' | null>(null)
  const [charServerError, setCharServerError] = useState<string | null>(null)
  const [analyzeError, setAnalyzeError] = useState<string | null>(null)

  const loadCharacters = useCallback(async () => {
    setCharsStatus('loading')
    setCharsError(null)
    try {
      setCharacters(await charactersApi.list(episodeId))
      setCharsStatus('ready')
    } catch (e) {
      setCharsError(errMsg(e, '加载角色失败'))
      setCharsStatus('error')
    }
  }, [episodeId])

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await analysisApi.listHistory(episodeId))
    } catch {
      // 历史列表为体验增强;失败不阻断主流程。
    }
  }, [episodeId])

  useEffect(() => {
    void loadCharacters()
    void loadHistory()
  }, [loadCharacters, loadHistory])

  const handleStart = useCallback(async () => {
    setAnalyzeError(null)
    try {
      await onStartAnalyze()
    } catch (e) {
      setAnalyzeError(errMsg(e, '发起拆解失败'))
    }
  }, [onStartAnalyze])

  const submitCharacter = useCallback(
    async (values: {
      name: string
      role_type: string
      persona: string
      motivation: string
      traits: string
      appearance_desc: string
    }) => {
      setCharServerError(null)
      const traits = splitTraits(values.traits)
      const id = charOverlay?.mode === 'edit' ? charOverlay.character.id : 'new'
      setCharBusy(id)
      try {
        if (charOverlay?.mode === 'edit') {
          await charactersApi.update(episodeId, charOverlay.character.id, {
            name: values.name,
            role_type: values.role_type || null,
            persona: values.persona || null,
            motivation: values.motivation || null,
            traits: traits.length ? traits : undefined,
            appearance_desc: values.appearance_desc || null,
          })
        } else {
          await charactersApi.create(episodeId, {
            name: values.name,
            role_type: values.role_type || null,
            persona: values.persona || null,
            motivation: values.motivation || null,
            traits: traits.length ? traits : undefined,
            appearance_desc: values.appearance_desc || null,
          })
        }
        setCharOverlay(null)
        await loadCharacters()
      } catch (e) {
        setCharServerError(errMsg(e, '保存角色失败'))
      } finally {
        setCharBusy(null)
      }
    },
    [charOverlay, episodeId, loadCharacters],
  )

  const deleteCharacter = useCallback(
    async (c: EpisodeCharacter) => {
      setCharBusy(c.id)
      try {
        await charactersApi.remove(episodeId, c.id)
        setConfirmDelete(null)
        await loadCharacters()
      } catch (e) {
        setCharsError(errMsg(e, '删除角色失败'))
      } finally {
        setCharBusy(null)
      }
    },
    [episodeId, loadCharacters],
  )

  const switchHistory = useCallback(
    async (analysisId: number) => {
      setHistoryBusy(true)
      setSwitchError(null)
      try {
        await analysisApi.selectCurrent(episodeId, { analysis_id: analysisId })
        await onSummaryRefresh()
      } catch (e) {
        setSwitchError(errMsg(e, '切换历史失败'))
      } finally {
        setHistoryBusy(false)
      }
    },
    [episodeId, onSummaryRefresh],
  )

  const current = summary?.current_analysis ?? null
  const presetChars = characters.filter((c) => c.source === 'preset')
  const analysisChars = characters.filter((c) => c.source === 'analysis')
  const currentAnalysisId = current?.id ?? null

  return (
    <div className="space-y-6">
      {/* 发起拆解 + 进度 */}
      <section className="space-y-3 rounded-lg border p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="font-medium">结构化拆解</h4>
          {configured ? (
            <Button onClick={() => void handleStart()} disabled={analyzing}>
              <Wand2 className="mr-2 size-4" />
              {analyzing ? '拆解中…' : '发起拆解'}
            </Button>
          ) : (
            <Badge variant="outline" className="text-amber-600 dark:text-amber-400">
              未配置文本模型
            </Badge>
          )}
        </div>
        {!configured ? (
          <p className="text-sm text-muted-foreground">
            拆解需要 active 文本模型。
            <Link to="/settings" className="ml-1 font-medium text-primary hover:underline">
              去配置 →
            </Link>
          </p>
        ) : null}
        {analyzeError ? (
          <p className="text-sm font-medium text-destructive">{analyzeError}</p>
        ) : null}
        {analyzing && analyzeTask ? (
          <div className="space-y-2 rounded-md border p-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">{analyzeTask.stage ?? '处理中'}</span>
              <span className="font-mono text-xs text-muted-foreground">
                {analyzeTask.progress}%
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full bg-primary transition-[width]"
                style={{ width: `${Math.max(2, analyzeTask.progress)}%` }}
              />
            </div>
            <Button variant="ghost" size="sm" onClick={() => void onCancelAnalyze()}>
              取消
            </Button>
          </div>
        ) : null}
      </section>

      {/* 四维结果(只读摘要) */}
      <section className="space-y-3">
        <h4 className="font-medium">拆解结果</h4>
        {current?.result ? (
          <AnalysisResultView result={current.result} />
        ) : (
          <p className="text-sm text-muted-foreground">
            {analyzing ? '拆解进行中,完成后在此呈现。' : '尚未拆解,或上次拆解未产出结果。'}
          </p>
        )}
      </section>

      {/* 历史 analysis 切换(D11;>1 时可切回历史分镜) */}
      {history.length > 1 ? (
        <section className="space-y-2 rounded-lg border p-4">
          <h4 className="font-medium">历史分析</h4>
          <p className="text-sm text-muted-foreground">
            切换 current 分析(同步影响分镜)。当前:
            {currentAnalysisId != null ? ` #${currentAnalysisId}` : ' 无'}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <select
              className={cn(SELECT_CLS, 'max-w-xs')}
              value={currentAnalysisId ?? ''}
              onChange={(e) => {
                const v = Number(e.target.value)
                if (Number.isInteger(v) && v > 0) void switchHistory(v)
              }}
              disabled={historyBusy}
            >
              {history.map((h) => (
                <option key={h.id} value={h.id}>
                  #{h.id} · {h.status} · {formatDateTime(h.created_at)}
                </option>
              ))}
            </select>
          </div>
          {switchError ? (
            <p className="text-sm font-medium text-destructive">{switchError}</p>
          ) : null}
        </section>
      ) : null}

      {/* 角色(D7 两源并列;无合并 UI) */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h4 className="font-medium">角色</h4>
          <Button variant="secondary" size="sm" onClick={() => setCharOverlay({ mode: 'create' })}>
            <Plus className="mr-1 size-4" /> 预置角色
          </Button>
        </div>
        {charsStatus === 'loading' ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner /> 加载中…
          </p>
        ) : charsStatus === 'error' ? (
          <p className="text-sm font-medium text-destructive">{charsError}</p>
        ) : (
          <div className="space-y-4">
            <CharacterGroup
              title="预置角色"
              empty="尚无预置角色。"
              items={presetChars}
              canEdit
              busy={charBusy}
              onEdit={(c) => setCharOverlay({ mode: 'edit', character: c })}
              onDelete={(c) => setConfirmDelete(c)}
            />
            <CharacterGroup
              title="拆解角色"
              empty="无(发起拆解后由 LLM 产出)。"
              items={analysisChars}
              note="由拆解产出(只读)"
            />
          </div>
        )}
      </section>

      {/* 新增 / 编辑角色 overlay */}
      {charOverlay ? (
        <Overlay
          title={charOverlay.mode === 'edit' ? '编辑预置角色' : '新增预置角色'}
          onClose={() => {
            setCharOverlay(null)
            setCharServerError(null)
          }}
        >
          <CharacterForm
            initial={
              charOverlay.mode === 'edit'
                ? {
                    name: charOverlay.character.name,
                    role_type: charOverlay.character.role_type ?? '',
                    persona: charOverlay.character.persona ?? '',
                    motivation: charOverlay.character.motivation ?? '',
                    traits: (charOverlay.character.traits ?? []).join(', '),
                    appearance_desc: charOverlay.character.appearance_desc ?? '',
                  }
                : undefined
            }
            submitLabel={charOverlay.mode === 'edit' ? '保存' : '新增'}
            submitting={charBusy != null}
            serverError={charServerError}
            onSubmit={submitCharacter}
          >
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setCharOverlay(null)
                setCharServerError(null)
              }}
            >
              取消
            </Button>
          </CharacterForm>
        </Overlay>
      ) : null}

      {/* 删除确认 */}
      {confirmDelete ? (
        <Overlay title="删除角色" onClose={() => setConfirmDelete(null)} maxWidthClass="max-w-sm">
          <p className="text-sm">
            确认删除预置角色「{confirmDelete.name}」?关联分镜出场将一并清除。
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmDelete(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={() => void deleteCharacter(confirmDelete)}
              disabled={charBusy != null}
            >
              {charBusy === confirmDelete.id ? <Spinner className="mr-2" /> : null}
              删除
            </Button>
          </div>
        </Overlay>
      ) : null}
    </div>
  )
}

/** 角色分组(preset 可编辑;analysis 只读 + note)。 */
function CharacterGroup({
  title,
  empty,
  items,
  canEdit = false,
  note,
  busy,
  onEdit,
  onDelete,
}: {
  title: string
  empty: string
  items: EpisodeCharacter[]
  canEdit?: boolean
  note?: string
  busy?: number | 'new' | null
  onEdit?: (c: EpisodeCharacter) => void
  onDelete?: (c: EpisodeCharacter) => void
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <h5 className="text-sm font-medium">{title}</h5>
        <span className="text-xs text-muted-foreground">{items.length}</span>
        {note ? (
          <Badge variant="outline" className="text-xs">
            {note}
          </Badge>
        ) : null}
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((c) => (
            <li key={c.id} className="rounded-md border p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{c.name}</span>
                {c.role_type ? (
                  <Badge variant="secondary" className="text-xs">
                    {c.role_type}
                  </Badge>
                ) : null}
                {canEdit ? (
                  <div className="ml-auto flex gap-1">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="编辑"
                      onClick={() => onEdit?.(c)}
                      disabled={busy != null}
                    >
                      <Pencil />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="删除"
                      onClick={() => onDelete?.(c)}
                      disabled={busy != null}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                ) : null}
              </div>
              {c.persona ? <p className="mt-1 text-muted-foreground">人设:{c.persona}</p> : null}
              {c.motivation ? (
                <p className="text-muted-foreground">动机:{c.motivation}</p>
              ) : null}
              {c.traits && c.traits.length ? (
                <div className="mt-1 flex flex-wrap gap-1">
                  {c.traits.map((t, i) => (
                    <Badge key={i} variant="outline" className="text-xs">
                      {t}
                    </Badge>
                  ))}
                </div>
              ) : null}
              {c.appearance_desc ? (
                <p className="mt-1 text-muted-foreground">外貌:{c.appearance_desc}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** 四维拆解结果只读视图(索引签名兜底,容忍提示词演进的额外字段)。 */
function AnalysisResultView({ result }: { result: AnalysisResult }) {
  const chars = result.characters ?? []
  const plotlines = result.plotlines ?? []
  const conflicts = result.conflicts ?? []
  const pacing = result.pacing
  return (
    <div className="space-y-4 rounded-lg border p-4 text-sm">
      <div>
        <h5 className="mb-1 font-medium">出场角色({chars.length})</h5>
        {chars.length === 0 ? (
          <p className="text-muted-foreground">无</p>
        ) : (
          <ul className="space-y-1">
            {chars.map((c, i) => (
              <li key={i}>
                <span className="font-medium">{c.name}</span>
                {c.role_type ? <span className="text-muted-foreground"> · {c.role_type}</span> : null}
                {c.persona ? <span className="text-muted-foreground"> — {c.persona}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <h5 className="mb-1 font-medium">情节线({plotlines.length})</h5>
        {plotlines.length === 0 ? (
          <p className="text-muted-foreground">无</p>
        ) : (
          <ul className="list-disc space-y-0.5 pl-5">
            {plotlines.map((p, i) => (
              <li key={i}>
                {p.name}
                {p.type ? <span className="text-muted-foreground"> · {p.type}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <h5 className="mb-1 font-medium">冲突({conflicts.length})</h5>
        {conflicts.length === 0 ? (
          <p className="text-muted-foreground">无</p>
        ) : (
          <ul className="space-y-0.5">
            {conflicts.map((c, i) => (
              <li key={i}>
                {c.type ? <span className="font-medium">{c.type}</span> : null}
                {c.parties ? <span className="text-muted-foreground"> — {c.parties}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <h5 className="mb-1 font-medium">节奏</h5>
        <p className="text-muted-foreground">
          {pacing?.structure ? `结构:${pacing.structure}` : '结构:—'}
        </p>
        {pacing?.climax ? (
          <p className="text-muted-foreground">高潮:{pacing.climax}</p>
        ) : null}
      </div>
    </div>
  )
}
