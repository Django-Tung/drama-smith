import { Navigate, useParams } from 'react-router-dom'

import { EpisodeWorkbench } from '@/features/episode/EpisodeWorkbench'

/**
 * 剧集工作台路由(薄,§13):取 `:episodeId` → 渲染 `<EpisodeWorkbench>`。
 * 工作台实现(剧本 / 拆解 / 分镜 三 tab)在 `features/episode`,本路由仅做参数解析 + 守卫。
 */
export function EpisodePage() {
  const { episodeId } = useParams()
  const id = Number(episodeId)
  if (!Number.isInteger(id) || id <= 0) return <Navigate to="/dramas" replace />

  return (
    <div className="mx-auto max-w-5xl">
      <EpisodeWorkbench episodeId={id} />
    </div>
  )
}
