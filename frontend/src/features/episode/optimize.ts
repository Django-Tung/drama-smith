/**
 * AI 优化任务产物的类型 + 收敛逻辑(D12)。从 `DiffView.tsx` 拆出,使后者只导出组件
 * (满足 `react-refresh/only-export-components`);本模块为纯数据域,无 React 依赖。
 */

/**
 * 后端 `difflib` 段落 diff 项(D12):`seg`=1-based 连续序号;`change_type`
 * ∈ `unchanged` / `added`(before="")/ `removed`(after="")/ `modified`。
 */
export interface DiffSegment {
  seg: number
  before: string
  after: string
  change_type: string
}

/** optimize 任务 succeeded 的 `output_refs` 收敛(D12):`{version_id, diff}`。 */
export interface OptimizeResult {
  version_id: number
  diff: DiffSegment[]
}

/**
 * 把 `Task.output_refs`(`Record<string, unknown> | null`)收敛为 `OptimizeResult`;
 * 形状不符(无 version_id / diff 非数组)→ null(调用方提示重试)。
 */
export function narrowOptimizeRefs(
  refs: Record<string, unknown> | null,
): OptimizeResult | null {
  if (!refs) return null
  const versionId = refs['version_id']
  const diff = refs['diff']
  if (typeof versionId !== 'number' || !Array.isArray(diff)) return null
  return { version_id: versionId, diff: diff as DiffSegment[] }
}
