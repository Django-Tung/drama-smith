import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '@/api/errors'
import { modelsApi } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { useAuthStore } from '@/stores/auth'
import type { ModelConfig, ModelConfigUpdate, ModelPurpose } from '@/types'

import { ModelConfigForm } from './ModelConfigForm'
import { providerLabel } from './providers'
import type { ConfigFormValues } from './schema'

const PURPOSES: ModelPurpose[] = ['text', 'image', 'video']
const PURPOSE_TITLE: Record<ModelPurpose, string> = {
  text: '文本模型',
  image: '图片模型',
  video: '视频模型',
}
const PURPOSE_HINT: Record<ModelPurpose, string> = {
  text: '必配(生效中至少一条方可使用文本能力)',
  image: '可选',
  video: '可选 · M3 接入(本期可保存,暂不支持自检)',
}

function errMsg(e: unknown, fallback: string): string {
  return ApiError.isApiError(e) ? e.message : fallback
}

interface EditTarget {
  purpose: ModelPurpose
  /** null = 新增;number = 编辑该 id。 */
  id: number | null
}

interface PendingDelete {
  cfg: ModelConfig
  siblings: ModelConfig[]
  chosen: number
}

/**
 * 模型配置管理(设置页):按用途分组,支持新增 / 编辑 / 设为生效 / 自检 / 删除。
 * 删「生效中」且同用途尚有兄弟 → 弹层要求选继任(对齐后端 6.2 invalid_state)。
 * 数据经本地态 + `modelsApi` 手动取/刷新(承接 M0 Zustand + manual 范式);
 * 变更后一并刷新 /api/me 以同步 `text_model_configured` 标记。
 */
export function ManageModels() {
  const refreshUser = useAuthStore((s) => s.refreshUser)
  const [configs, setConfigs] = useState<ModelConfig[]>([])
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [edit, setEdit] = useState<EditTarget | null>(null)
  const [busyId, setBusyId] = useState<number | 'form' | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null)

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      setConfigs(await modelsApi.list())
      setStatus('ready')
    } catch (e) {
      setLoadError(errMsg(e, '加载模型配置失败'))
      setStatus('error')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const reload = async () => {
    await load()
    await refreshUser()
  }

  const byPurpose = (p: ModelPurpose): ModelConfig[] => configs.filter((c) => c.purpose === p)
  const siblingsOf = (cfg: ModelConfig): ModelConfig[] =>
    byPurpose(cfg.purpose).filter((c) => c.id !== cfg.id)

  const onActivate = async (cfg: ModelConfig) => {
    setActionError(null)
    setBusyId(cfg.id)
    try {
      await modelsApi.activate(cfg.id)
      await reload()
    } catch (e) {
      setActionError(errMsg(e, '激活失败'))
    } finally {
      setBusyId(null)
    }
  }

  const onTest = async (cfg: ModelConfig) => {
    setActionError(null)
    setBusyId(cfg.id)
    try {
      await modelsApi.test(cfg.id)
      await reload()
    } catch (e) {
      setActionError(errMsg(e, '自检失败:Key 无效或被限流'))
    } finally {
      setBusyId(null)
    }
  }

  const onDelete = (cfg: ModelConfig) => {
    setActionError(null)
    if (cfg.is_active && siblingsOf(cfg).length > 0) {
      const sibs = siblingsOf(cfg)
      setPendingDelete({ cfg, siblings: sibs, chosen: sibs[0].id })
      return
    }
    void doDelete(cfg.id)
  }

  const doDelete = async (id: number, newActiveId?: number) => {
    setBusyId(id)
    try {
      await modelsApi.delete(id, newActiveId)
      await reload()
    } catch (e) {
      setActionError(errMsg(e, '删除失败'))
    } finally {
      setBusyId(null)
    }
  }

  const confirmDelete = async () => {
    if (!pendingDelete) return
    const { cfg, chosen } = pendingDelete
    setPendingDelete(null)
    await doDelete(cfg.id, chosen)
  }

  const submitForm = async (target: EditTarget, v: ConfigFormValues) => {
    setActionError(null)
    setBusyId('form')
    try {
      if (target.id == null) {
        await modelsApi.create({
          purpose: target.purpose,
          provider: v.provider,
          model: v.model,
          api_key: v.api_key,
          base_url: v.base_url || null,
        })
      } else {
        const upd: ModelConfigUpdate = {
          provider: v.provider,
          model: v.model,
          base_url: v.base_url || null,
        }
        if (v.api_key) upd.api_key = v.api_key // 留空 → 不换 Key(D8)
        await modelsApi.update(target.id, upd)
      }
      await reload()
      setEdit(null)
    } catch (e) {
      setActionError(errMsg(e, '保存失败'))
    } finally {
      setBusyId(null)
    }
  }

  if (status === 'loading') return <p className="text-sm text-muted-foreground">加载模型配置…</p>
  if (status === 'error')
    return (
      <div className="space-y-2">
        <p className="text-sm font-medium text-destructive">{loadError}</p>
        <Button variant="outline" size="sm" onClick={() => void load()}>
          重试
        </Button>
      </div>
    )

  return (
    <div className="space-y-6">
      {PURPOSES.map((purpose) => {
        const list = byPurpose(purpose)
        const editingThis = edit?.purpose === purpose ? edit : null
        const editingCfg =
          editingThis?.id != null ? configs.find((c) => c.id === editingThis.id) : undefined
        return (
          <section key={purpose} className="space-y-2">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-medium">{PURPOSE_TITLE[purpose]}</h3>
                <p className="text-xs text-muted-foreground">{PURPOSE_HINT[purpose]}</p>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={edit != null}
                onClick={() => setEdit({ purpose, id: null })}
              >
                新增
              </Button>
            </div>

            {editingThis ? (
              <Card>
                <CardContent className="pt-4">
                  <ModelConfigForm
                    purpose={purpose}
                    requireKey={editingThis.id == null}
                    initial={
                      editingCfg
                        ? {
                            provider: editingCfg.provider,
                            model: editingCfg.model,
                            base_url: editingCfg.base_url ?? '',
                          }
                        : undefined
                    }
                    submitLabel={editingThis.id == null ? '保存' : '更新'}
                    submitting={busyId === 'form'}
                    serverError={editingThis.id === edit?.id ? actionError : null}
                    onSubmit={(v) => void submitForm(editingThis, v)}
                  >
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => setEdit(null)}
                      disabled={busyId === 'form'}
                    >
                      取消
                    </Button>
                  </ModelConfigForm>
                </CardContent>
              </Card>
            ) : null}

            {list.length === 0 ? (
              <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                尚未配置
              </p>
            ) : (
              <div className="space-y-2">
                {list.map((cfg) => (
                  <ConfigItem
                    key={cfg.id}
                    cfg={cfg}
                    busy={busyId === cfg.id}
                    onActivate={() => void onActivate(cfg)}
                    onTest={() => void onTest(cfg)}
                    onEdit={() => setEdit({ purpose, id: cfg.id })}
                    onDelete={() => onDelete(cfg)}
                  />
                ))}
              </div>
            )}
          </section>
        )
      })}

      {actionError && edit == null ? (
        <p className="text-sm font-medium text-destructive">{actionError}</p>
      ) : null}

      {pendingDelete ? (
        <DeleteSuccessorOverlay
          pending={pendingDelete}
          onChoose={(id) => setPendingDelete({ ...pendingDelete, chosen: id })}
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => void confirmDelete()}
        />
      ) : null}
    </div>
  )
}

interface ConfigItemProps {
  cfg: ModelConfig
  busy: boolean
  onActivate: () => void
  onTest: () => void
  onEdit: () => void
  onDelete: () => void
}

function ConfigItem({ cfg, busy, onActivate, onTest, onEdit, onDelete }: ConfigItemProps) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border p-3">
      <div className="space-y-1 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{providerLabel(cfg.provider)}</span>
          <span className="text-muted-foreground">{cfg.model}</span>
          {cfg.is_active ? <Badge>生效中</Badge> : null}
          {cfg.status === 'invalid' ? <Badge variant="destructive">无效</Badge> : null}
        </div>
        <div className="text-xs text-muted-foreground">Key {cfg.api_key_masked}</div>
        <div className="text-xs text-muted-foreground">
          {cfg.last_tested_at
            ? `自检于 ${new Date(cfg.last_tested_at).toLocaleString()}`
            : '尚未自检'}
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-stretch gap-1 sm:flex-row sm:flex-wrap">
        {!cfg.is_active ? (
          <Button size="sm" variant="outline" disabled={busy} onClick={onActivate}>
            设为生效
          </Button>
        ) : null}
        {cfg.purpose !== 'video' ? (
          <Button size="sm" variant="outline" disabled={busy} onClick={onTest}>
            自检
          </Button>
        ) : null}
        <Button size="sm" variant="ghost" disabled={busy} onClick={onEdit}>
          编辑
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onDelete}>
          删除
        </Button>
      </div>
    </div>
  )
}

interface DeleteSuccessorOverlayProps {
  pending: PendingDelete
  onChoose: (id: number) => void
  onCancel: () => void
  onConfirm: () => void
}

/** 删除「生效中」配置时的继任选择弹层(无 shadcn dialog,用轻量遮罩)。 */
function DeleteSuccessorOverlay({
  pending,
  onChoose,
  onCancel,
  onConfirm,
}: DeleteSuccessorOverlayProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-sm space-y-3 rounded-lg border bg-background p-4 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h4 className="font-medium">删除生效配置</h4>
        <p className="text-sm text-muted-foreground">
          删除「{providerLabel(pending.cfg.provider)} / {pending.cfg.model}」会令该用途暂无生效配置。
          请选择一条同用途配置接替为生效:
        </p>
        <div className="space-y-1">
          {pending.siblings.map((s) => (
            <label
              key={s.id}
              className="flex cursor-pointer items-center gap-2 rounded-md border p-2 text-sm"
            >
              <input
                type="radio"
                name="successor"
                checked={pending.chosen === s.id}
                onChange={() => onChoose(s.id)}
              />
              <span className="font-medium">{providerLabel(s.provider)}</span>
              <span className="text-muted-foreground">{s.model}</span>
            </label>
          ))}
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" size="sm" onClick={onCancel}>
            取消
          </Button>
          <Button variant="destructive" size="sm" onClick={onConfirm}>
            确认删除
          </Button>
        </div>
      </div>
    </div>
  )
}
