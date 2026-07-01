import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

/** 我的剧库(占位,FR-A1):登录后落地页,剧集列表将在此呈现。 */
export function DramasPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="font-serif text-2xl font-semibold">我的剧库</h1>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>开发中</CardTitle>
          <CardDescription>剧集列表(FR-A1)与「新建剧集」入口将在此呈现。</CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          地基已就绪,后续 feature 在 AppShell 内容区拼装。
        </CardContent>
      </Card>
    </div>
  )
}
