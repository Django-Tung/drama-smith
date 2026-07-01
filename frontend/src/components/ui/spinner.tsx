import * as React from 'react'
import { Loader2 } from 'lucide-react'

import { cn } from '@/utils/cn'

/**
 * 加载旋转指示器:lucide 的 Loader2 + animate-spin。
 * 默认弱化色 + size-4,可用 className 覆盖尺寸/颜色。
 */
function Spinner({ className, ...props }: React.ComponentProps<typeof Loader2>) {
  return (
    <Loader2
      data-slot="spinner"
      className={cn('size-4 animate-spin text-muted-foreground', className)}
      {...props}
    />
  )
}

export { Spinner }
