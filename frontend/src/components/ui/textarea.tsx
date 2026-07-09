import * as React from 'react'

import { cn } from '@/utils/cn'

/**
 * 多行文本输入(无 Radix 依赖;样式对齐 `Input`)。
 * forwardRef 以支持 React Hook Form 的 `register()`(同 `Input`)。用于剧本正文、
 * 镜描述 / 对白等多行字段。
 */
const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.ComponentProps<'textarea'>
>(function Textarea({ className, ...props }, ref) {
  return (
    <textarea
      ref={ref}
      data-slot="textarea"
      className={cn(
        'flex min-h-20 w-full min-w-0 rounded-md border border-input bg-transparent px-3 py-2 text-base shadow-xs transition-[color,box-shadow] outline-none placeholder:text-muted-foreground disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:bg-input/30',
        'focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50',
        'aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40',
        className,
      )}
      {...props}
    />
  )
})

export { Textarea }
