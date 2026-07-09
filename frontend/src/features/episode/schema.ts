import { z } from 'zod'

/**
 * 预置角色表单校验(新增 / 编辑复用)。`traits` 在表单中为「逗号 / 分号 / 顿号 / 换行」
 * 分隔的字符串(无数组字段原语),提交时由 `splitTraits` 拆为 `string[]`。
 *
 * 可选字段一律 `z.string()`(表单默认 ''),提交时空串由调用方省略键(对齐后端
 * `extra="forbid"` + 可选字段缺省存 null 的语义)。
 */
export const characterSchema = z.object({
  name: z.string().trim().min(1, '请输入角色名').max(100, '角色名过长'),
  role_type: z.string().trim().max(50, '角色类型过长'),
  persona: z.string().trim().max(500, '人设过长'),
  motivation: z.string().trim().max(500, '动机过长'),
  traits: z.string().trim().max(500, '特征过长'),
  appearance_desc: z.string().trim().max(500, '外貌描述过长'),
})

export type CharacterFormValues = z.infer<typeof characterSchema>

/** 把表单的 traits 字符串拆为字符串数组(去空白 / 去空)。 */
export function splitTraits(raw: string): string[] {
  return raw
    .split(/[,;\n、]/)
    .map((t) => t.trim())
    .filter(Boolean)
}
