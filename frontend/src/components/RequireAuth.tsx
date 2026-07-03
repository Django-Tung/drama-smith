import { type ReactNode, useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'

import { authApi } from '@/api/endpoints'
import { refreshSession } from '@/api/client'
import { Spinner } from '@/components/ui/spinner'
import { useAuthStore } from '@/stores/auth'

interface RequireAuthProps {
  children: ReactNode
}

type Status = 'checking' | 'ready' | 'rejected'

/**
 * 路由守卫(frontend.md §3):
 * 1) 无 access → 凭 refresh 刷新;刷新失败 / 无 refresh → 重定向 `/login`;
 * 2) 确保 `auth.user` 已加载(GET /api/me,access 过期由 client 透明刷新)。
 *
 * 即:进入受保护页面前,会话有效 + 当前用户已就绪;后续请求的 401 仍由 client 透明刷新。
 */
export function RequireAuth({ children }: RequireAuthProps) {
  const accessToken = useAuthStore((s) => s.accessToken)
  const refreshToken = useAuthStore((s) => s.refreshToken)
  const setUser = useAuthStore((s) => s.setUser)
  // /setup → / 等跨 RequireAuth 实例跳转时,user 多已就绪 → 直接放行,避免 Spinner 闪现。
  const [status, setStatus] = useState<Status>(() =>
    accessToken && useAuthStore.getState().user ? 'ready' : 'checking',
  )

  useEffect(() => {
    let active = true
    void (async () => {
      try {
        if (!accessToken) {
          if (!refreshToken) {
            setStatus('rejected')
            return
          }
          await refreshSession()
        }
        if (!useAuthStore.getState().user) {
          const me = await authApi.getMe()
          if (!active) return
          setUser(me)
        }
        if (active) setStatus('ready')
      } catch {
        if (active) setStatus('rejected')
      }
    })()
    return () => {
      active = false
    }
  }, [accessToken, refreshToken, setUser])

  if (status === 'rejected') return <Navigate to="/login" replace />
  if (status === 'checking') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Spinner className="size-6" />
      </div>
    )
  }
  return <>{children}</>
}
