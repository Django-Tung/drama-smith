import { type ReactNode, useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'

import { refreshSession } from '@/api/client'
import { Spinner } from '@/components/ui/spinner'
import { useAuthStore } from '@/stores/auth'

interface RequireAuthProps {
  children: ReactNode
}

type Status = 'checking' | 'ready' | 'rejected'

/**
 * 路由守卫(frontend.md §3):无 access → 尝试刷新;刷新失败(或无 refresh)→
 * 重定向 `/login`。access 在手则直接放行(后续请求的 401 由 client 透明刷新)。
 */
export function RequireAuth({ children }: RequireAuthProps) {
  const accessToken = useAuthStore((s) => s.accessToken)
  const refreshToken = useAuthStore((s) => s.refreshToken)
  const [status, setStatus] = useState<Status>(accessToken ? 'ready' : 'checking')

  useEffect(() => {
    if (accessToken) {
      setStatus('ready')
      return
    }
    if (!refreshToken) {
      setStatus('rejected')
      return
    }
    let active = true
    refreshSession()
      .then(() => {
        if (active) setStatus('ready')
      })
      .catch(() => {
        if (active) setStatus('rejected')
      })
    return () => {
      active = false
    }
  }, [accessToken, refreshToken])

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
