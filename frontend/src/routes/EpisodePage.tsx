import { Navigate, useParams } from 'react-router-dom'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

/**
 * 剧集工作台路由(薄,§13):取 `:episodeId` → 渲染工作台。
 * 工作台实现(剧本 / 拆解 / 分镜 三 tab)在 `features/episode`,本路由仅做参数解析 + 守卫。
 */
export function EpisodePage() {
  const { episodeId } = useParams()
  const id = Number(episodeId)
  if (!Number.isInteger(id) || id <= 0) return <Navigate to="/dramas" replace />

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="font-serif text-2xl font-semibold">剧集工作台</h1>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>开发中</CardTitle>
          <CardDescription>
            剧本输入 + AI 优化 + 角色拆解 + 分镜编辑台将在此呈现(episode #{id})。
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          工作台组件在后续批次拼装。
        </CardContent>
      </Card>
    </div>
  )
}
