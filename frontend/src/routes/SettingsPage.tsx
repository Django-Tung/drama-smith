import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ManageModels } from '@/features/ai-config/ManageModels'
import { useAuthStore } from '@/stores/auth'

/** 设置:账户信息 + BYOK 模型配置(FR-C2)。 */
export function SettingsPage() {
  const user = useAuthStore((s) => s.user)

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="font-serif text-2xl font-semibold">设置</h1>
        <p className="text-sm text-muted-foreground">账户信息与 BYOK 模型配置</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>账户</CardTitle>
          <CardDescription>个人信息</CardDescription>
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

      <Card>
        <CardHeader>
          <CardTitle>模型配置</CardTitle>
          <CardDescription>
            管理文本 / 图片 / 视频模型凭证(BYOK)。明文 Key 不落本地,仅显示脱敏串。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ManageModels />
        </CardContent>
      </Card>
    </div>
  )
}
