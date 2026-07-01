import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuthStore } from '@/stores/auth'

/** 设置(占位,FR-C2):个人信息 + 模型配置。此处先承接 /api/me 的账户态。 */
export function SettingsPage() {
  const user = useAuthStore((s) => s.user)

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="font-serif text-2xl font-semibold">设置</h1>
      <Card className="mt-4">
        <CardHeader>
          <CardTitle>账户</CardTitle>
          <CardDescription>个人信息与 BYOK 模型配置(FR-C2)将在此完善。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">用户名</span>
            <span className="font-medium">{user?.username ?? '加载中…'}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">文本模型</span>
            <Badge variant={user?.text_model_configured ? 'default' : 'secondary'}>
              {user?.text_model_configured ? '已配置' : '未配置'}
            </Badge>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
