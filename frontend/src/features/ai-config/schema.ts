import { z } from 'zod'

import { isWhitelisted } from './providers'

/**
 * 模型配置表单校验(向导 / 设置页新增 + 编辑复用)。
 *
 * - `provider` 须落在 `purpose` 白名单内(对齐后端 `model_validator`,前端先挡 →
 *   越界不会发到后端);
 * - 创建模式 `requireKey`(默认):`api_key` 必填;编辑模式置 false → 留空表示
 *   不换 Key(D8:缺省不动加密列)。
 */
export function configFormSchema(
  purpose: 'text' | 'image' | 'video',
  opts: { requireKey?: boolean } = {},
) {
  const requireKey = opts.requireKey ?? true
  return z
    .object({
      provider: z.string().min(1, '请选择供应商'),
      model: z.string().min(1, '请填写模型标识').max(128),
      // api_key 恒为 string(避免 edit 模式 optional 导致 resolver 推断类型与表单泛型不一致);
      // 「必填」规则在 superRefine 内按 requireKey 施加,edit 模式留空即「不换 Key」(D8)。
      api_key: z.string().max(512),
      base_url: z
        .string()
        .max(512)
        .url('base_url 须为合法 URL')
        .or(z.literal(''))
        .optional(),
    })
    .superRefine((val, ctx) => {
      if (!isWhitelisted(purpose, val.provider)) {
        ctx.addIssue({
          path: ['provider'],
          code: 'custom',
          message: '该供应商不支持此用途',
        })
      }
      if (requireKey && val.api_key.length < 1) {
        ctx.addIssue({ path: ['api_key'], code: 'custom', message: '请填写 API Key' })
      }
    })
}

export type ConfigFormValues = z.infer<ReturnType<typeof configFormSchema>>
