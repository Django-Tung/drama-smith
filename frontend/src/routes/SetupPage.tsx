import { Navigate } from 'react-router-dom'

import { Wizard } from '@/features/ai-config/Wizard'
import { useAuthStore } from '@/stores/auth'

/**
 * 初始化向导页(`/setup`,受 `RequireAuth` 保护但绕过 `RequireSetup`)。
 * 已配置文本模型 → 直接回主页(无需向导)。
 */
export function SetupPage() {
  const user = useAuthStore((s) => s.user)
  if (user?.text_model_configured) return <Navigate to="/dramas" replace />
  return <Wizard />
}
