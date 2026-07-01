import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * 条件合并 Tailwind 类:clsx 做条件拼接,twMerge 解决冲突(后者覆盖前者,如 px-2 vs px-4)。
 * shadcn/ui 组件统一用此工具拼 className。
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
