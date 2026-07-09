import type { ReactNode } from 'react'

import { cn } from '@/utils/cn'

interface OverlayProps {
  /** 面板标题。 */
  title: string
  /** 面板内容(含操作按钮;按钮由调用方提供)。 */
  children: ReactNode
  /** 点遮罩 / Esc 关闭(调用方决定是否允许;此处仅绑定遮罩点击)。 */
  onClose: () => void
  /** 面板最大宽度 class;默认 `max-w-md`。 */
  maxWidthClass?: string
}

/**
 * 通用轻量遮罩(无 shadcn dialog 依赖)。复用 M1 `DeleteSuccessorOverlay` 范式:
 * `fixed inset-0 z-50 bg-black/40` 全屏遮罩 + 居中面板;点遮罩关闭、点面板内不关闭
 * (`stopPropagation`)。内容(表单 / 确认文案 + 按钮)由 `children` 提供。
 */
export function Overlay({ title, children, onClose, maxWidthClass = 'max-w-md' }: OverlayProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        className={cn(
          'w-full space-y-4 rounded-lg border bg-background p-4 shadow-lg',
          maxWidthClass,
        )}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <h4 className="font-medium">{title}</h4>
        {children}
      </div>
    </div>
  )
}
