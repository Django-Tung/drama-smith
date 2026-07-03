import { type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { useAuthStore } from '@/stores/auth'

interface RequireSetupProps {
  children: ReactNode
}

/**
 * 文本模型配置门禁(design D11):未配置 active 文本配置 → 重定向 `/setup` 向导。
 * `user` 已由 `RequireAuth` 预加载;此处据 `text_model_configured` 决定放行。
 * `/setup` 本身不经此守卫(避免循环重定向)。
 */
export function RequireSetup({ children }: RequireSetupProps) {
  const user = useAuthStore((s) => s.user)
  if (user && !user.text_model_configured) return <Navigate to="/setup" replace />
  return <>{children}</>
}
