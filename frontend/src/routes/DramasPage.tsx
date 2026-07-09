import { useEffect, useState } from 'react'
import { Clapperboard, Plus, Pencil, Trash2, ChevronRight, Film } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { Overlay } from '@/components/Overlay'
import { Field } from '@/components/Field'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { ApiError } from '@/api/errors'
import { useLibraryStore } from '@/stores/library'
import { cn } from '@/utils/cn'
import type { AspectRatio, Drama, Episode } from '@/types'

/** 原生 select 样式,贴近 Input(无 shadcn select 原语)。 */
const SELECT_CLS =
  'h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50'

const ASPECT_RATIOS: AspectRatio[] = ['16:9', '9:16', '1:1', '4:3']

const STATUS_LABEL: Record<Episode['status'], string> = {
  draft: '草稿',
  analyzing: '拆解中',
  ready: '已拆解',
  rendering: '渲染中',
  done: '已完成',
}

function errMsg(e: unknown, fallback: string): string {
  return ApiError.isApiError(e) ? e.message : fallback
}

/** 单字段表单(剧名 / 剧集标题重命名复用;字段少,不引 zod)。 */
function NameForm({
  label,
  placeholder,
  initial,
  submitLabel,
  busy,
  serverError,
  onSubmit,
  onCancel,
}: {
  label: string
  placeholder?: string
  initial?: string
  submitLabel: string
  busy: boolean
  serverError: string | null
  onSubmit: (value: string) => void
  onCancel: () => void
}) {
  const [value, setValue] = useState(initial ?? '')
  const submit = () => {
    const v = value.trim()
    if (v) onSubmit(v)
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
      className="space-y-3"
    >
      <Field label={label} htmlFor="name-field" error={serverError ?? undefined}>
        <Input
          id="name-field"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
          autoFocus
        />
      </Field>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={busy}>
          取消
        </Button>
        <Button type="submit" size="sm" disabled={busy || !value.trim()}>
          {busy ? '处理中…' : submitLabel}
        </Button>
      </div>
    </form>
  )
}

/** 新建剧集表单(标题 + 画幅 + 风格预设)。 */
function EpisodeCreateForm({
  busy,
  serverError,
  onSubmit,
  onCancel,
}: {
  busy: boolean
  serverError: string | null
  onSubmit: (v: { title: string; aspect_ratio: AspectRatio; style_preset: string | null }) => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState('')
  const [aspect, setAspect] = useState<AspectRatio>('16:9')
  const [style, setStyle] = useState('')
  const submit = () => {
    const t = title.trim()
    if (!t) return
    onSubmit({ title: t, aspect_ratio: aspect, style_preset: style.trim() || null })
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
      className="space-y-3"
    >
      <Field label="剧集标题" htmlFor="ep-title" error={serverError ?? undefined}>
        <Input
          id="ep-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="如:第一集 · 开端"
          autoFocus
        />
      </Field>
      <Field label="画幅" htmlFor="ep-aspect">
        <select
          id="ep-aspect"
          className={SELECT_CLS}
          value={aspect}
          onChange={(e) => setAspect(e.target.value as AspectRatio)}
        >
          {ASPECT_RATIOS.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </Field>
      <Field label="风格预设(可选)" htmlFor="ep-style">
        <Input
          id="ep-style"
          value={style}
          onChange={(e) => setStyle(e.target.value)}
          placeholder="如:都市悬疑、轻喜剧"
        />
      </Field>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={busy}>
          取消
        </Button>
        <Button type="submit" size="sm" disabled={busy || !title.trim()}>
          {busy ? '处理中…' : '创建'}
        </Button>
      </div>
    </form>
  )
}

/** `dramaOverlay` 联合:新建 / 重命名剧。 */
type DramaOverlay = { mode: 'create' } | { mode: 'rename'; drama: Drama }
/** `episodeOverlay` 联合:新建 / 重命名剧集。 */
type EpisodeOverlay = { mode: 'create'; dramaId: number } | { mode: 'rename'; episode: Episode }
/** 删除确认(剧 / 剧集)。 */
type ConfirmDelete =
  | { kind: 'drama'; drama: Drama }
  | { kind: 'episode'; episode: Episode }

/**
 * 我的剧库(§13.1 实现版,替换占位)。master-detail:剧目列表 → 选中剧展开其剧集;
 * 剧 / 剧集两级新建 / 重命名 / 软删。数据走 `useLibraryStore`(D10:Zustand + 手动 request);
 * 瞬态(表单 / 弹层 / 行内 busy)用本地态。点剧集 → 进工作台 `/episodes/:id`。
 */
export function DramasPage() {
  const navigate = useNavigate()
  const dramas = useLibraryStore((s) => s.dramas)
  const dramasStatus = useLibraryStore((s) => s.dramasStatus)
  const dramasError = useLibraryStore((s) => s.dramasError)
  const selectedDramaId = useLibraryStore((s) => s.selectedDramaId)
  const episodes = useLibraryStore((s) => s.episodes)
  const episodesStatus = useLibraryStore((s) => s.episodesStatus)
  const episodesError = useLibraryStore((s) => s.episodesError)
  const loadDramas = useLibraryStore((s) => s.loadDramas)
  const selectDrama = useLibraryStore((s) => s.selectDrama)

  const selectedDrama = dramas.find((d) => d.id === selectedDramaId) ?? null

  const [dramaOverlay, setDramaOverlay] = useState<DramaOverlay | null>(null)
  const [episodeOverlay, setEpisodeOverlay] = useState<EpisodeOverlay | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<ConfirmDelete | null>(null)
  const [busy, setBusy] = useState(false)
  const [overlayError, setOverlayError] = useState<string | null>(null)

  useEffect(() => {
    if (dramasStatus === 'idle') void loadDramas()
  }, [dramasStatus, loadDramas])

  // ---- 剧写操作 ----
  const submitDrama = async (value: string) => {
    if (!dramaOverlay) return
    setBusy(true)
    setOverlayError(null)
    try {
      if (dramaOverlay.mode === 'create') {
        const d = await useLibraryStore.getState().createDrama(value)
        await selectDrama(d.id) // 新建后直接展开
      } else {
        await useLibraryStore.getState().renameDrama(dramaOverlay.drama.id, value)
      }
      setDramaOverlay(null)
    } catch (e) {
      setOverlayError(errMsg(e, '保存失败'))
    } finally {
      setBusy(false)
    }
  }

  // ---- 剧集写操作 ----
  const submitEpisodeCreate = async (
    dramaId: number,
    v: { title: string; aspect_ratio: AspectRatio; style_preset: string | null },
  ) => {
    setBusy(true)
    setOverlayError(null)
    try {
      await useLibraryStore.getState().createEpisode(dramaId, v)
      setEpisodeOverlay(null)
    } catch (e) {
      setOverlayError(errMsg(e, '创建剧集失败'))
    } finally {
      setBusy(false)
    }
  }

  const submitEpisodeRename = async (id: number, title: string) => {
    setBusy(true)
    setOverlayError(null)
    try {
      await useLibraryStore.getState().renameEpisode(id, title)
      setEpisodeOverlay(null)
    } catch (e) {
      setOverlayError(errMsg(e, '重命名失败'))
    } finally {
      setBusy(false)
    }
  }

  const doDelete = async () => {
    if (!confirmDelete) return
    setBusy(true)
    setOverlayError(null)
    try {
      if (confirmDelete.kind === 'drama') {
        await useLibraryStore.getState().deleteDrama(confirmDelete.drama.id)
      } else {
        await useLibraryStore.getState().deleteEpisode(confirmDelete.episode.id)
      }
      setConfirmDelete(null)
    } catch (e) {
      setOverlayError(errMsg(e, '删除失败'))
    } finally {
      setBusy(false)
    }
  }

  if (dramasStatus === 'loading')
    return (
      <div className="mx-auto max-w-4xl">
        <h1 className="font-serif text-2xl font-semibold">我的剧库</h1>
        <p className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner className="size-4" /> 加载剧目…
        </p>
      </div>
    )

  if (dramasStatus === 'error')
    return (
      <div className="mx-auto max-w-4xl space-y-2">
        <h1 className="font-serif text-2xl font-semibold">我的剧库</h1>
        <p className="text-sm font-medium text-destructive">{dramasError}</p>
        <Button variant="outline" size="sm" onClick={() => void loadDramas()}>
          重试
        </Button>
      </div>
    )

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="font-serif text-2xl font-semibold">我的剧库</h1>
        <Button size="sm" onClick={() => setDramaOverlay({ mode: 'create' })}>
          <Plus className="size-4" /> 新建剧
        </Button>
      </div>

      {/* 剧目列表 */}
      {dramas.length === 0 ? (
        <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
          还没有剧。点「新建剧」开始创作。
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {dramas.map((d) => (
            <div
              key={d.id}
              className={cn(
                'rounded-lg border p-4 transition-colors',
                selectedDramaId === d.id ? 'border-primary bg-accent/40' : 'hover:bg-accent/30',
              )}
            >
              <button
                className="flex w-full items-start gap-3 text-left"
                onClick={() => void selectDrama(d.id)}
              >
                <Clapperboard className="mt-0.5 size-5 shrink-0 text-primary" />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{d.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {new Date(d.created_at).toLocaleDateString()} 创建
                  </div>
                </div>
              </button>
              <div className="mt-3 flex justify-end gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setDramaOverlay({ mode: 'rename', drama: d })}
                >
                  <Pencil className="size-3.5" /> 重命名
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-destructive hover:text-destructive"
                  onClick={() => setConfirmDelete({ kind: 'drama', drama: d })}
                >
                  <Trash2 className="size-3.5" /> 删除
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 选中剧的剧集列表 */}
      {selectedDrama ? (
        <section className="space-y-3 border-t pt-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="flex items-center gap-2 font-serif text-lg font-semibold">
                <Film className="size-4 text-primary" /> 《{selectedDrama.name}》的剧集
              </h2>
              <p className="text-xs text-muted-foreground">点剧集进入工作台。</p>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                setEpisodeOverlay({ mode: 'create', dramaId: selectedDrama.id })
              }
            >
              <Plus className="size-4" /> 新建剧集
            </Button>
          </div>

          {episodesStatus === 'loading' ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Spinner className="size-4" /> 加载剧集…
            </p>
          ) : episodesStatus === 'error' ? (
            <p className="text-sm font-medium text-destructive">{episodesError}</p>
          ) : episodes.length === 0 ? (
            <p className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground">
              该剧尚无剧集。
            </p>
          ) : (
            <ul className="divide-y rounded-lg border">
              {episodes.map((ep) => (
                <li key={ep.id} className="flex items-center gap-3 p-3">
                  <button
                    className="flex min-w-0 flex-1 items-center gap-3 text-left"
                    onClick={() => navigate(`/episodes/${ep.id}`)}
                  >
                    <span className="truncate font-medium">{ep.title}</span>
                    <Badge variant="outline" className="shrink-0">
                      {ep.aspect_ratio}
                    </Badge>
                    {ep.status !== 'draft' ? (
                      <Badge variant="secondary" className="shrink-0">
                        {STATUS_LABEL[ep.status]}
                      </Badge>
                    ) : null}
                    {ep.style_preset ? (
                      <span className="truncate text-xs text-muted-foreground">
                        {ep.style_preset}
                      </span>
                    ) : null}
                  </button>
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setEpisodeOverlay({ mode: 'rename', episode: ep })}
                  >
                    重命名
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-destructive hover:text-destructive"
                    onClick={() => setConfirmDelete({ kind: 'episode', episode: ep })}
                  >
                    删除
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}

      {/* 弹层:剧名新建 / 重命名 */}
      {dramaOverlay ? (
        <Overlay
          title={dramaOverlay.mode === 'create' ? '新建剧' : '重命名剧'}
          onClose={() => setDramaOverlay(null)}
        >
          <NameForm
            label="剧名"
            placeholder="如:都市悬疑系列"
            initial={dramaOverlay.mode === 'rename' ? dramaOverlay.drama.name : undefined}
            submitLabel={dramaOverlay.mode === 'create' ? '创建' : '保存'}
            busy={busy}
            serverError={overlayError}
            onSubmit={submitDrama}
            onCancel={() => setDramaOverlay(null)}
          />
        </Overlay>
      ) : null}

      {/* 弹层:剧集新建 / 重命名 */}
      {episodeOverlay ? (
        <Overlay
          title={episodeOverlay.mode === 'create' ? '新建剧集' : '重命名剧集'}
          onClose={() => setEpisodeOverlay(null)}
        >
          {episodeOverlay.mode === 'create' ? (
            <EpisodeCreateForm
              busy={busy}
              serverError={overlayError}
              onSubmit={(v) => void submitEpisodeCreate(episodeOverlay.dramaId, v)}
              onCancel={() => setEpisodeOverlay(null)}
            />
          ) : (
            <NameForm
              label="剧集标题"
              placeholder="如:第一集"
              initial={episodeOverlay.episode.title}
              submitLabel="保存"
              busy={busy}
              serverError={overlayError}
              onSubmit={(v) => void submitEpisodeRename(episodeOverlay.episode.id, v)}
              onCancel={() => setEpisodeOverlay(null)}
            />
          )}
        </Overlay>
      ) : null}

      {/* 弹层:删除确认 */}
      {confirmDelete ? (
        <Overlay
          title={confirmDelete.kind === 'drama' ? '删除剧' : '删除剧集'}
          onClose={() => setConfirmDelete(null)}
          maxWidthClass="max-w-sm"
        >
          <p className="text-sm text-muted-foreground">
            {confirmDelete.kind === 'drama'
              ? `确定删除剧「${confirmDelete.drama.name}」?其下剧集将一并软删,后续可恢复。`
              : `确定删除剧集「${confirmDelete.episode.title}」?`}
          </p>
          {overlayError ? (
            <p className="text-sm font-medium text-destructive">{overlayError}</p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setConfirmDelete(null)}
              disabled={busy}
            >
              取消
            </Button>
            <Button type="button" variant="destructive" size="sm" disabled={busy} onClick={doDelete}>
              {busy ? '处理中…' : '确认删除'}
            </Button>
          </div>
        </Overlay>
      ) : null}
    </div>
  )
}
