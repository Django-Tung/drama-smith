import { Badge } from '@/components/ui/badge'
import { cn } from '@/utils/cn'

import type { DiffSegment } from './optimize'

/** change_type → 文案 + 着色(未知类型按 modified 处理)。 */
const TYPE_META: Record<string, { label: string; cls: string }> = {
  unchanged: { label: '未改', cls: 'text-muted-foreground' },
  added: { label: '新增', cls: 'text-emerald-600 dark:text-emerald-400' },
  removed: { label: '删除', cls: 'text-destructive line-through' },
  modified: { label: '修改', cls: 'text-amber-600 dark:text-amber-400' },
}

/**
 * 只读段落 diff 渲染(D12):整版接受 / 拒绝,**无段落勾选 / 部分采纳**。
 * added 仅显 after、removed 仅显 before、modified 前后对照、unchanged 显 after(muted)。
 */
export function DiffView({ diff }: { diff: DiffSegment[] }) {
  if (diff.length === 0) {
    return <p className="text-sm text-muted-foreground">无差异(两版一致)。</p>
  }
  return (
    <div className="space-y-2">
      {diff.map((seg) => {
        const meta = TYPE_META[seg.change_type] ?? TYPE_META.modified
        return (
          <div key={seg.seg} className="rounded-md border p-2 text-sm">
            <div className="mb-1 flex items-center gap-2">
              <Badge variant="outline" className="text-xs font-mono">
                #{seg.seg}
              </Badge>
              <Badge variant="secondary" className={cn('text-xs', meta.cls)}>
                {meta.label}
              </Badge>
            </div>
            {seg.change_type === 'added' ? (
              <pre className={cn('whitespace-pre-wrap font-serif', meta.cls)}>{seg.after}</pre>
            ) : seg.change_type === 'removed' ? (
              <pre className={cn('whitespace-pre-wrap font-serif', meta.cls)}>{seg.before}</pre>
            ) : seg.change_type === 'modified' ? (
              <div className="space-y-1">
                <pre className="whitespace-pre-wrap font-serif text-destructive line-through">
                  {seg.before}
                </pre>
                <pre className="whitespace-pre-wrap font-serif text-emerald-600 dark:text-emerald-400">
                  {seg.after}
                </pre>
              </div>
            ) : (
              <pre className="whitespace-pre-wrap font-serif text-muted-foreground">
                {seg.after}
              </pre>
            )}
          </div>
        )
      })}
    </div>
  )
}
