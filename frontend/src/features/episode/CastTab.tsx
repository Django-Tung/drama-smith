import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Pencil, Plus, Trash2, Upload, Wand2 } from 'lucide-react'

import { ApiError } from '@/api/errors'
import { analysisApi, charactersApi } from '@/api/endpoints'
import { useAuthStore } from '@/stores/auth'
import { Avatar } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Overlay } from '@/components/Overlay'
import { Spinner } from '@/components/ui/spinner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useTaskPolling } from '@/hooks/useTaskPolling'
import { cn } from '@/utils/cn'
import { formatDateTime } from '@/utils/format'
import type {
  Analysis,
  AnalysisResult,
  AnalysisSummary,
  EpisodeCharacter,
  MediaPublic,
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
  const imageConfigured = useAuthStore((s) => s.user?.image_model_configured) ?? false
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
              episodeId={episodeId}
              imageConfigured={imageConfigured}
              title="预置角色"
              empty="尚无预置角色。"
              items={presetChars}
              canEdit
              busy={charBusy}
              onEdit={(c) => setCharOverlay({ mode: 'edit', character: c })}
              onDelete={(c) => setConfirmDelete(c)}
            />
            <CharacterGroup
              episodeId={episodeId}
              imageConfigured={imageConfigured}
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

/** 角色分组(preset 可编辑;analysis 只读 + note);每卡含形象图(上传 / AI 生成)。 */
function CharacterGroup({
  episodeId,
  imageConfigured,
  title,
  empty,
  items,
  canEdit = false,
  note,
  busy,
  onEdit,
  onDelete,
}: {
  episodeId: number
  imageConfigured: boolean
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
            <CharacterCard
              key={c.id}
              episodeId={episodeId}
              character={c}
              imageConfigured={imageConfigured}
              canEdit={canEdit}
              busy={busy}
              onEdit={onEdit}
              onDelete={onDelete}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * 单角色卡(character-media §9.4):头像展示 + 文本字段 + 形象图上传 / AI 生成。
 * - 头像:`getPortrait` 拉签名 URL(`<Avatar>` 直用);挂载 / 上传 / 生成终态后刷新。
 * - 上传:隐藏 `<input type=file accept=image/*>` → `uploadPortrait`(201)→ 刷新头像。
 * - AI 生成:`generatePortrait`(202)→ `useTaskPolling` 终态 succeeded 后刷新头像。
 * - 门禁:`image_model_configured` 假 或 `appearance_desc` 空 → 禁用「AI 生成」+ tooltip 提示。
 *   (形象图为角色附加属性,preset / analysis 两源均可上传 / 生成,与文本字段是否可编辑解耦。)
 */
function CharacterCard({
  episodeId,
  character,
  imageConfigured,
  canEdit,
  busy,
  onEdit,
  onDelete,
}: {
  episodeId: number
  character: EpisodeCharacter
  imageConfigured: boolean
  canEdit?: boolean
  /** 全局角色 CRUD 在途编号(与 CharacterGroup 一致);文本字段按钮据此禁用。 */
  busy?: number | 'new' | null
  onEdit?: (c: EpisodeCharacter) => void
  onDelete?: (c: EpisodeCharacter) => void
}) {
  const [portrait, setPortrait] = useState<MediaPublic | null>(null)
  const [uploading, setUploading] = useState(false)
  const [imageTaskId, setImageTaskId] = useState<number | null>(null)
  const [imageError, setImageError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadPortrait = useCallback(async () => {
    try {
      setPortrait(await charactersApi.getPortrait(episodeId, character.id))
    } catch {
      // 形象图为体验增强;加载失败不阻断卡片(204 无图已得 null)。
    }
  }, [episodeId, character.id])

  useEffect(() => {
    void loadPortrait()
  }, [loadPortrait])

  const { task: imageTask, cancel: cancelImage } = useTaskPolling(imageTaskId, {
    onTerminal: (t) => {
      setImageTaskId(null)
      if (t.status === 'succeeded') {
        void loadPortrait()
        return
      }
      const msg = t.error?.message
      setImageError(typeof msg === 'string' ? msg : t.status === 'canceled' ? '已取消' : '生成失败')
    },
  })

  const appearanceFilled = (character.appearance_desc ?? '').trim() !== ''
  const canGen = imageConfigured && appearanceFilled
  const textBusy = busy != null
  const cardBusy = uploading || imageTask != null

  const handleFile = useCallback(
    async (file: File) => {
      setUploading(true)
      setImageError(null)
      try {
        setPortrait(await charactersApi.uploadPortrait(episodeId, character.id, file))
      } catch (e) {
        setImageError(errMsg(e, '上传失败'))
      } finally {
        setUploading(false)
      }
    },
    [episodeId, character.id],
  )

  const handleGenerate = useCallback(async () => {
    setImageError(null)
    try {
      const task = await charactersApi.generatePortrait(episodeId, character.id)
      setImageTaskId(task.id)
    } catch (e) {
      setImageError(errMsg(e, '发起生成失败'))
    }
  }, [episodeId, character.id])

  return (
    <li className="rounded-md border p-3 text-sm">
      <div className="flex items-start gap-3">
        <Avatar
          src={portrait?.signed_url}
          name={character.name}
          size={40}
          className={cn(uploading && 'opacity-60')}
        />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{character.name}</span>
            {character.role_type ? (
              <Badge variant="secondary" className="text-xs">
                {character.role_type}
              </Badge>
            ) : null}
            {canEdit ? (
              <div className="ml-auto flex gap-1">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="编辑"
                  onClick={() => onEdit?.(character)}
                  disabled={textBusy}
                >
                  <Pencil />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="删除"
                  onClick={() => onDelete?.(character)}
                  disabled={textBusy}
                >
                  <Trash2 />
                </Button>
              </div>
            ) : null}
          </div>
          {character.persona ? (
            <p className="text-muted-foreground">人设:{character.persona}</p>
          ) : null}
          {character.motivation ? (
            <p className="text-muted-foreground">动机:{character.motivation}</p>
          ) : null}
          {character.traits && character.traits.length ? (
            <div className="flex flex-wrap gap-1">
              {character.traits.map((t, i) => (
                <Badge key={i} variant="outline" className="text-xs">
                  {t}
                </Badge>
              ))}
            </div>
          ) : null}
          {character.appearance_desc ? (
            <p className="text-muted-foreground">外貌:{character.appearance_desc}</p>
          ) : null}

          {/* 形象图操作:上传(multipart)+ AI 生成(异步轮询);门禁禁用 AI 生成 */}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                e.target.value = '' // 允许重复选同一文件
                if (f) void handleFile(f)
              }}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
              disabled={cardBusy}
            >
              <Upload />
              {uploading ? '上传中…' : portrait ? '更换图片' : '上传图片'}
            </Button>
            {canGen ? (
              <Button size="sm" onClick={() => void handleGenerate()} disabled={cardBusy}>
                <Wand2 />
                {imageTask ? '生成中…' : 'AI 生成'}
              </Button>
            ) : (
              <Tooltip>
                {/* span 包裹:disabled 按钮自身不收 pointer 事件,用 span 承载 hover 显 tooltip */}
                <TooltipTrigger asChild>
                  <span tabIndex={0} className="inline-flex">
                    <Button size="sm" disabled>
                      <Wand2 />
                      AI 生成
                    </Button>
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  {imageConfigured ? '需先填写「外貌描述」' : '未配置图片模型,去「设置」开启'}
                </TooltipContent>
              </Tooltip>
            )}
          </div>

          {imageTask ? (
            <div className="space-y-1 rounded-md border p-2">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{imageTask.stage ?? '生成中'}</span>
                <span className="font-mono">{imageTask.progress}%</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full bg-primary transition-[width]"
                  style={{ width: `${Math.max(2, imageTask.progress)}%` }}
                />
              </div>
              <Button variant="ghost" size="xs" onClick={() => void cancelImage()}>
                取消
              </Button>
            </div>
          ) : null}
          {imageError ? <p className="text-sm font-medium text-destructive">{imageError}</p> : null}
        </div>
      </div>
    </li>
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
