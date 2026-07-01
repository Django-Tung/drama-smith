import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

/** 任务中心(占位,FR-A11):跨剧集任务汇总 + 进度,前台 WS / 后台轮询(§8)。 */
export function TasksPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="font-serif text-2xl font-semibold">任务中心</h1>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>开发中</CardTitle>
          <CardDescription>任务列表(状态/剧集/时间过滤)+ 进度条 + 错误(FR-A11)。</CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          实时进度将走 WebSocket + 断线轮询回退(frontend.md §8)。
        </CardContent>
      </Card>
    </div>
  )
}
