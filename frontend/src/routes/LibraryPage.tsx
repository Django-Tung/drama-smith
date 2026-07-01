import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

/** 角色库(占位,FR-L):公共角色库列表将在此呈现。 */
export function LibraryPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="font-serif text-2xl font-semibold">角色库</h1>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>开发中</CardTitle>
          <CardDescription>公共角色库(FR-L)与 promote/clone 入口将在此呈现。</CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">地基已就绪,待接入。</CardContent>
      </Card>
    </div>
  )
}
