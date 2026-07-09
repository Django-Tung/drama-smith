import { useCallback, useEffect, useState } from 'react'
import { GitMerge } from 'lucide-react'

import { ApiError } from '@/api/errors'
import { charactersApi, shotsApi } from '@/api/endpoints'
import { Field } from '@/components/Field'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Overlay } from '@/components/Overlay'
import { Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'
import type { EpisodeCharacter, Shot, ShotPatch, ShotType } from '@/types'
import { ShotRow } from './ShotRow'

/** 原生 select 样式,贴近 Input(无 shadcn select 原语)。 */
const SELECT_CLS =
  'h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50'

const SHOT_TYPES: { value: ShotType; label: string }[] = [
  { value: 'wide', label: '远景' },
  { value: 'medium', label: '中景' },
  { value: 'close', label: '近景' },
  { value: 'extreme_close', label: '特写' },
]

function errMsg(e: unknown, fallback: string): string {
  return ApiError.isApiError(e) ? e.message : fallback
}

/**
 * 分镜编辑台(§13.4)。挂在 current_analysis 名下:`currentAnalysisId` 为 null(未拆解)
 * → 空态。组件随 tab 切换 unmount/remount,故 current_analysis 变更(重拆 / 历史切换)
 * 后回到本 tab 自动重拉。
 *
 * - 排序:↑/↓ → 重算 ordered_ids → reorder → 用返回 Shot[]。
 * - 行内编辑:见 `<ShotRow>`;patch 局部更新单镜。
 * - 拆:Overlay 表单(description 必填)→ split → 全量重拉(seq 位移)。
 * - 合:与下一镜合并确认 → merge({into_shot_id: next.id});跨 analysis → 409 → 内联错误。
 */
export function ShotsEditor({
  episodeId,
  currentAnalysisId,
}: {
  episodeId: number
  currentAnalysisId: number | null
}) {
  const [shots, setShots] = useState<Shot[]>([])
  const [characters, setCharacters] = useState<EpisodeCharacter[]>([])
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)
  const [reorderBusy, setReorderBusy] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)

  const [splitShot, setSplitShot] = useState<Shot | null>(null)
  const [splitDesc, setSplitDesc] = useState('')
  const [splitType, setSplitType] = useState<string>('')
  const [splitDur, setSplitDur] = useState('')
  const [splitError, setSplitError] = useState<string | null>(null)

  const [mergeShot, setMergeShot] = useState<Shot | null>(null)
  const [mergeError, setMergeError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (currentAnalysisId == null) {
      setShots([])
      setStatus('ready')
      return
    }
    setStatus('loading')
    setError(null)
    try {
      const [s, c] = await Promise.all([
        shotsApi.list(episodeId),
        charactersApi.list(episodeId),
      ])
      setShots(s)
      setCharacters(c)
      setStatus('ready')
    } catch (e) {
      setError(errMsg(e, '加载分镜失败'))
      setStatus('error')
    }
  }, [episodeId, currentAnalysisId])

  useEffect(() => {
    void load()
  }, [load])

  const handleSave = useCallback(
    async (shotId: number, patch: ShotPatch) => {
      setBusyId(shotId)
      try {
        const res = await shotsApi.patch(shotId, patch)
        setShots((prev) => prev.map((s) => (s.id === res.shot.id ? res.shot : s)))
      } catch (e) {
        setError(errMsg(e, '保存分镜失败'))
        throw e
      } finally {
        setBusyId(null)
      }
    },
    [],
  )

  const move = useCallback(
    async (shot: Shot, dir: 'up' | 'down') => {
      const ordered = [...shots].sort((a, b) => a.seq - b.seq)
      const idx = ordered.findIndex((s) => s.id === shot.id)
      const target = dir === 'up' ? idx - 1 : idx + 1
      if (idx < 0 || target < 0 || target >= ordered.length) return
      const ids = ordered.map((s) => s.id)
      const tmp = ids[idx]
      ids[idx] = ids[target]
      ids[target] = tmp
      setReorderBusy(true)
      try {
        const updated = await shotsApi.reorder(episodeId, { ordered_ids: ids })
        setShots(updated)
      } catch (e) {
        setError(errMsg(e, '重排失败'))
      } finally {
        setReorderBusy(false)
      }
    },
    [episodeId, shots],
  )

  const openSplit = useCallback((shot: Shot) => {
    setSplitShot(shot)
    setSplitDesc('')
    setSplitType('')
    setSplitDur('')
    setSplitError(null)
  }, [])

  const doSplit = useCallback(async () => {
    if (!splitShot) return
    const desc = splitDesc.trim()
    if (!desc) {
      setSplitError('新镜描述不能为空')
      return
    }
    setBusyId(splitShot.id)
    try {
      await shotsApi.split(splitShot.id, {
        description: desc,
        shot_type: (splitType || undefined) as ShotType | undefined,
        target_duration: splitDur === '' ? undefined : Number(splitDur),
      })
      setSplitShot(null)
      await load()
    } catch (e) {
      setSplitError(errMsg(e, '拆分失败'))
    } finally {
      setBusyId(null)
    }
  }, [splitShot, splitDesc, splitType, splitDur, load])

  const openMerge = useCallback((shot: Shot) => {
    setMergeShot(shot)
    setMergeError(null)
  }, [])

  const doMerge = useCallback(async () => {
    if (!mergeShot) return
    const ordered = [...shots].sort((a, b) => a.seq - b.seq)
    const idx = ordered.findIndex((s) => s.id === mergeShot.id)
    const next = ordered[idx + 1]
    if (!next) return
    setBusyId(mergeShot.id)
    try {
      await shotsApi.merge(mergeShot.id, { into_shot_id: next.id })
      setMergeShot(null)
      await load()
    } catch (e) {
      setMergeError(errMsg(e, '合并失败(可能跨分析)'))
    } finally {
      setBusyId(null)
    }
  }, [mergeShot, shots, load])

  const ordered = [...shots].sort((a, b) => a.seq - b.seq)
  const disabledAll = reorderBusy || splitShot != null || mergeShot != null

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="font-medium">
          分镜编辑
          {currentAnalysisId != null ? (
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              共 {ordered.length} 镜
            </span>
          ) : null}
        </h4>
      </div>
      {error ? <p className="text-sm font-medium text-destructive">{error}</p> : null}

      {currentAnalysisId == null ? (
        <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
          尚未拆解,无法编辑分镜。先在「角色与拆解」发起拆解。
        </p>
      ) : status === 'loading' ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner /> 加载中…
        </p>
      ) : status === 'error' ? (
        <p className="text-sm font-medium text-destructive">{error}</p>
      ) : ordered.length === 0 ? (
        <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
          本次拆解未产出分镜。
        </p>
      ) : (
        <ul className="space-y-2">
          {ordered.map((shot, i) => (
            <li key={shot.id}>
              <ShotRow
                shot={shot}
                characters={characters}
                isFirst={i === 0}
                isLast={i === ordered.length - 1}
                disabled={disabledAll}
                saving={busyId === shot.id}
                onSave={(patch) => handleSave(shot.id, patch)}
                onSplit={() => openSplit(shot)}
                onMerge={() => openMerge(shot)}
                onMoveUp={() => void move(shot, 'up')}
                onMoveDown={() => void move(shot, 'down')}
              />
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">
        目标时长越界(∉ 3–15s)以琥珀色标注,不阻断保存。
      </p>

      {/* 拆分 overlay(在此镜后插入新镜;description 必填) */}
      {splitShot ? (
        <Overlay
          title={`在 #${splitShot.seq} 后插入新镜`}
          onClose={() => setSplitShot(null)}
        >
          <div className="space-y-3">
            <Field label="新镜描述" htmlFor="split-desc" error={splitError ?? undefined}>
              <Textarea
                id="split-desc"
                value={splitDesc}
                onChange={(e) => setSplitDesc(e.target.value)}
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="景别(可选)" htmlFor="split-type">
                <select
                  id="split-type"
                  className={SELECT_CLS}
                  value={splitType}
                  onChange={(e) => setSplitType(e.target.value)}
                >
                  <option value="">—</option>
                  {SHOT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="目标时长(可选,秒)" htmlFor="split-dur">
                <Input
                  id="split-dur"
                  type="number"
                  min={3}
                  max={15}
                  step={1}
                  value={splitDur}
                  onChange={(e) => setSplitDur(e.target.value)}
                />
              </Field>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setSplitShot(null)}>
                取消
              </Button>
              <Button onClick={() => void doSplit()} disabled={busyId != null}>
                插入
              </Button>
            </div>
          </div>
        </Overlay>
      ) : null}

      {/* 合并确认(与下一镜) */}
      {mergeShot ? (
        <Overlay title="合并分镜" onClose={() => setMergeShot(null)} maxWidthClass="max-w-sm">
          <MergeConfirmBody
            mergeShot={mergeShot}
            shots={ordered}
            busy={busyId != null}
            error={mergeError}
            onCancel={() => setMergeShot(null)}
            onConfirm={() => void doMerge()}
          />
        </Overlay>
      ) : null}
    </div>
  )
}

/** 合并确认正文:展示当前镜 + 下一镜,确认后 merge。 */
function MergeConfirmBody({
  mergeShot,
  shots,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  mergeShot: Shot
  shots: Shot[]
  busy: boolean
  error: string | null
  onCancel: () => void
  onConfirm: () => void
}) {
  const idx = shots.findIndex((s) => s.id === mergeShot.id)
  const next = shots[idx + 1]
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm">
        <GitMerge className="size-4 text-muted-foreground" />
        <span>
          合并「#{mergeShot.seq}」{next ? ` 与「#${next.seq}」` : ''}?
        </span>
      </div>
      {next ? (
        <p className="text-sm text-muted-foreground">
          合并后保留为「#{mergeShot.seq}」,下一镜删除(须属同一分析)。
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">已是最后一镜,无可合并对象。</p>
      )}
      {error ? <p className="text-sm font-medium text-destructive">{error}</p> : null}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          取消
        </Button>
        <Button onClick={onConfirm} disabled={busy || !next}>
          确认合并
        </Button>
      </div>
    </div>
  )
}
