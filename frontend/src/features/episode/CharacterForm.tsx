import { zodResolver } from '@hookform/resolvers/zod'
import type { ReactNode } from 'react'
import { useForm } from 'react-hook-form'

import { Field } from '@/components/Field'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { type CharacterFormValues, characterSchema } from './schema'

interface CharacterFormProps {
  /** 编辑模式预填(traits 为已 join 的字符串);新增省略。 */
  initial?: Partial<CharacterFormValues>
  submitLabel: string
  submitting: boolean
  serverError?: string | null
  onSubmit: (values: CharacterFormValues) => void | Promise<void>
  /** 额外操作槽位(如「取消」)。 */
  children?: ReactNode
}

/**
 * 预置角色表单(新增 / 编辑复用,在 `<Overlay>` 内使用)。RHF + zod,镜像 M1
 * `ModelConfigForm` 范式。traits 以逗号分隔单行输入 → 提交时拆数组(由调用方)。
 */
export function CharacterForm({
  initial,
  submitLabel,
  submitting,
  serverError,
  onSubmit,
  children,
}: CharacterFormProps) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CharacterFormValues>({
    resolver: zodResolver(characterSchema),
    defaultValues: {
      name: initial?.name ?? '',
      role_type: initial?.role_type ?? '',
      persona: initial?.persona ?? '',
      motivation: initial?.motivation ?? '',
      traits: initial?.traits ?? '',
      appearance_desc: initial?.appearance_desc ?? '',
    },
  })

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <Field label="角色名" htmlFor="char-name" error={errors.name?.message}>
        <Input id="char-name" autoComplete="off" {...register('name')} />
      </Field>
      <Field label="角色类型(可选)" htmlFor="char-role" error={errors.role_type?.message}>
        <Input id="char-role" placeholder="如 主角 / 配角 / 反派" {...register('role_type')} />
      </Field>
      <Field label="人设(可选)" htmlFor="char-persona" error={errors.persona?.message}>
        <Textarea id="char-persona" {...register('persona')} />
      </Field>
      <Field label="动机(可选)" htmlFor="char-motiv" error={errors.motivation?.message}>
        <Textarea id="char-motiv" {...register('motivation')} />
      </Field>
      <Field label="特征(可选,逗号分隔)" htmlFor="char-traits" error={errors.traits?.message}>
        <Input id="char-traits" placeholder="如 勇敢,固执,善良" {...register('traits')} />
      </Field>
      <Field
        label="外貌描述(可选)"
        htmlFor="char-look"
        error={errors.appearance_desc?.message}
      >
        <Textarea id="char-look" {...register('appearance_desc')} />
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
