import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useRef, type ReactNode } from 'react'
import { useForm } from 'react-hook-form'

import { Field } from '@/components/Field'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { ModelPurpose } from '@/types'

import { PROVIDERS, defaultModel, providerLabel } from './providers'
import { type ConfigFormValues, configFormSchema } from './schema'

interface ModelConfigFormProps {
  purpose: ModelPurpose
  /** 编辑模式预填(不含明文 key);新增模式省略。 */
  initial?: Partial<ConfigFormValues>
  /** 编辑模式置 false:api_key 可留空(不换 Key,D8)。 */
  requireKey?: boolean
  submitLabel: string
  submitting: boolean
  serverError?: string | null
  onSubmit: (values: ConfigFormValues) => void | Promise<void>
  /** 额外操作槽位(如「跳过」/「完成」)。 */
  children?: ReactNode
}

/** 原生 select,样式贴近 Input。 */
const SELECT_CLS =
  'h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50'

export function ModelConfigForm({
  purpose,
  initial,
  requireKey = true,
  submitLabel,
  submitting,
  serverError,
  onSubmit,
  children,
}: ModelConfigFormProps) {
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<ConfigFormValues>({
    resolver: zodResolver(configFormSchema(purpose, { requireKey })),
    defaultValues: {
      provider: initial?.provider ?? PROVIDERS[purpose][0],
      model: initial?.model ?? '',
      api_key: initial?.api_key ?? '',
      base_url: initial?.base_url ?? '',
    },
  })

  const provider = watch('provider')
  const prevProvider = useRef(provider)
  // 切换供应商:若 model 为空或仍是旧供应商的默认值 → 自动填入新默认(用户手填的不覆盖)。
  useEffect(() => {
    if (provider === prevProvider.current) return
    const cur = watch('model')
    const wasDefault = !cur || cur === defaultModel(purpose, prevProvider.current)
    const next = defaultModel(purpose, provider)
    if (wasDefault && next) setValue('model', next, { shouldDirty: true })
    prevProvider.current = provider
  }, [provider, purpose, setValue, watch])

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <Field label="供应商" htmlFor="provider" error={errors.provider?.message}>
        <select id="provider" className={SELECT_CLS} {...register('provider')}>
          {PROVIDERS[purpose].map((p) => (
            <option key={p} value={p}>
              {providerLabel(p)}
            </option>
          ))}
        </select>
      </Field>
      <Field label="模型标识" htmlFor="model" error={errors.model?.message}>
        <Input id="model" placeholder="如 gpt-4o-mini" {...register('model')} />
      </Field>
      <Field
        label="API Key"
        htmlFor="api_key"
        error={errors.api_key?.message}
      >
        <Input
          id="api_key"
          type="password"
          autoComplete="off"
          placeholder={requireKey ? '明文仅本次加密,不落本地' : '留空表示不更换 Key'}
          {...register('api_key')}
        />
      </Field>
      <Field label="Base URL(可选)" htmlFor="base_url" error={errors.base_url?.message}>
        <Input
          id="base_url"
          placeholder="OpenAI 兼容地址,留空用默认"
          {...register('base_url')}
        />
      </Field>
      {serverError ? <p className="text-sm font-medium text-destructive">{serverError}</p> : null}
      <div className="flex items-center gap-2">
        <Button type="submit" disabled={submitting}>
          {submitting ? '处理中…' : submitLabel}
        </Button>
        {children}
      </div>
    </form>
  )
}
