import { useState } from 'react'
import { Check, ChevronDown, ChevronUp, GitMerge, Pencil, Split, X } from 'lucide-react'

import { Field } from '@/components/Field'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/utils/cn'
import { durationIssue, isDurationOutOfRange } from '@/utils/format'
import type { EpisodeCharacter, Shot, ShotPatch, ShotType } from '@/types'

/** 原生 select 样式,贴近 Input(无 shadcn select 原语);与各 tab 同款。 */
const SELECT_CLS =
  'h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50'

const SHOT_TYPES: { value: ShotType; label: string }[] = [
  { value: 'wide', label: '远景' },
  { value: 'medium', label: '中景' },
  { value: 'close', label: '近景' },
  { value: 'extreme_close', label: '特写' },
]

const DURATION_ISSUE_LABEL: Record<string, string> = {
  too_short: '过短(<3s)',
  too_long: '过长(>15s)',
}

interface ShotRowProps {
  shot: Shot
  /** 全剧集角色(出场勾选用;preset + analysis 两源)。 */
  characters: EpisodeCharacter[]
  isFirst: boolean
  isLast: boolean
  /** 全局重排 / 拆 / 合进行中 → 禁用所有操作。 */
  disabled: boolean
  /** 本镜保存中。 */
  saving: boolean
  onSave: (patch: ShotPatch) => Promise<void>
  onSplit: () => void
  onMerge: () => void
  onMoveUp: () => void
  onMoveDown: () => void
}

/**
 * 单分镜行(§13.4):行内编辑(描述 / 景别 / 时长 / 对白 / 出场)+ 排序(↑/↓)+
 * 拆 / 合触发。越界时长(D5)→ 琥珀边 + 内联「过短 / 过长」,**不阻断保存**。
 * 拆 / 合只触发回调(overlay + API 在 `ShotsEditor`)。
 */
export function ShotRow({
  shot,
  characters,
  isFirst,
  isLast,
  disabled,
  saving,
  onSave,
  onSplit,
  onMerge,
  onMoveUp,
  onMoveDown,
}: ShotRowProps) {
  const [editing, setEditing] = useState(false)
  const [description, setDescription] = useState(shot.description)
  const [dialogue, setDialogue] = useState(shot.dialogue ?? '')
  const [shotType, setShotType] = useState<string>(shot.shot_type ?? '')
  const [duration, setDuration] = useState<string>(
    shot.target_duration == null ? '' : String(shot.target_duration),
  )
  const [appearingIds, setAppearingIds] = useState<Set<number>>(
    new Set(shot.appearing.map((a) => a.episode_character_id)),
  )
  const [formError, setFormError] = useState<string | null>(null)

  const committedIssue = durationIssue(shot.target_duration)
  const outOfRange = isDurationOutOfRange(shot.target_duration)

  const startEdit = () => {
    setDescription(shot.description)
    setDialogue(shot.dialogue ?? '')
    setShotType(shot.shot_type ?? '')
    setDuration(shot.target_duration == null ? '' : String(shot.target_duration))
    setAppearingIds(new Set(shot.appearing.map((a) => a.episode_character_id)))
    setFormError(null)
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
    setFormError(null)
  }

  const toggleAppearing = (id: number) => {
    setAppearingIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const submit = async () => {
    const desc = description.trim()
    if (!desc) {
      setFormError('镜描述不能为空')
      return
    }
    const patch: ShotPatch = {
      description: desc,
      dialogue: dialogue.trim(),
      shot_type: (shotType || undefined) as ShotPatch['shot_type'],
      target_duration: duration === '' ? undefined : Number(duration),
      appearing: Array.from(appearingIds),
    }
    try {
      await onSave(patch)
      setEditing(false)
    } catch {
      // onSave 失败已由 editor 置 error;保持编辑态供重试。
    }
  }

  // 编辑态时长越界:实时高亮(提交值仍可能越界,不阻断)。
  const editingDurationIssue =
    editing && duration !== '' ? durationIssue(Number(duration)) : null

  return (
    <div
      className={cn(
        'space-y-2 rounded-md border p-3 text-sm',
        outOfRange ? 'border-amber-400/70 dark:border-amber-500/50' : '',
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-muted-foreground">#{shot.seq}</span>
        {shot.shot_type ? (
          <Badge variant="secondary" className="text-xs">
            {SHOT_TYPES.find((t) => t.value === shot.shot_type)?.label ?? shot.shot_type}
          </Badge>
        ) : null}
        {shot.target_duration != null ? (
          <Badge variant="outline" className="text-xs">
            {shot.target_duration}s
          </Badge>
        ) : null}
        {committedIssue ? (
          <span className="text-xs font-medium text-amber-600 dark:text-amber-400">
            {DURATION_ISSUE_LABEL[committedIssue]}
          </span>
        ) : null}
        <span className="ml-auto" />
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="上移"
          onClick={onMoveUp}
          disabled={isFirst || disabled || editing}
        >
          <ChevronUp />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="下移"
          onClick={onMoveDown}
          disabled={isLast || disabled || editing}
        >
          <ChevronDown />
        </Button>
        {editing ? (
          <>
            <Button variant="ghost" size="sm" onClick={cancelEdit} disabled={saving}>
              <X className="mr-1 size-4" /> 取消
            </Button>
            <Button size="sm" onClick={() => void submit()} disabled={saving}>
              {saving ? null : <Check className="mr-1 size-4" />} 保存
            </Button>
          </>
        ) : (
          <>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="编辑"
              onClick={startEdit}
              disabled={disabled}
            >
              <Pencil />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="在此后拆分"
              onClick={onSplit}
              disabled={disabled}
              title="在此镜后插入新镜"
            >
              <Split />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="与下一镜合并"
              onClick={onMerge}
              disabled={isLast || disabled}
              title="与下一镜合并"
            >
              <GitMerge />
            </Button>
          </>
        )}
      </div>

      {editing ? (
        <div className="space-y-3">
          <Field label="镜描述" htmlFor={`shot-desc-${shot.id}`} error={formError ?? undefined}>
            <Textarea
              id={`shot-desc-${shot.id}`}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="景别" htmlFor={`shot-type-${shot.id}`}>
              <select
                id={`shot-type-${shot.id}`}
                className={SELECT_CLS}
                value={shotType}
                onChange={(e) => setShotType(e.target.value)}
              >
                <option value="">—</option>
                {SHOT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="目标时长(秒)"
              htmlFor={`shot-dur-${shot.id}`}
              error={editingDurationIssue ? DURATION_ISSUE_LABEL[editingDurationIssue] : undefined}
            >
              <Input
                id={`shot-dur-${shot.id}`}
                type="number"
                min={3}
                max={15}
                step={1}
                value={duration}
                onChange={(e) => setDuration(e.target.value)}
              />
            </Field>
          </div>
          <Field label="对白" htmlFor={`shot-dlg-${shot.id}`}>
            <Textarea
              id={`shot-dlg-${shot.id}`}
              value={dialogue}
              onChange={(e) => setDialogue(e.target.value)}
            />
          </Field>
          <Field label="出场角色">
            {characters.length === 0 ? (
              <p className="text-muted-foreground">本剧无角色。</p>
            ) : (
              <div className="flex flex-wrap gap-x-4 gap-y-1.5">
                {characters.map((c) => (
                  <label
                    key={c.id}
                    className="flex items-center gap-1.5 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={appearingIds.has(c.id)}
                      onChange={() => toggleAppearing(c.id)}
                    />
                    {c.name}
                  </label>
                ))}
              </div>
            )}
          </Field>
        </div>
      ) : (
        <div className="space-y-1">
          <p className="whitespace-pre-wrap">{shot.description}</p>
          {shot.dialogue ? (
            <p className="whitespace-pre-wrap font-serif text-muted-foreground">
              「{shot.dialogue}」
            </p>
          ) : null}
          {shot.appearing.length ? (
            <p className="text-xs text-muted-foreground">
              出场:{shot.appearing.map((a) => a.name).join('、')}
            </p>
          ) : null}
        </div>
      )}
    </div>
  )
}
