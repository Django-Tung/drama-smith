import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { authApi } from '@/api/endpoints'
import { ApiError } from '@/api/errors'
import { useAuthStore } from '@/stores/auth'
import type { User } from '@/types'

/**
 * 受保护首页(占位)。登录后落地,拉取 `/api/me` 展示当前用户;
 * 若 access 过期,getMe 的 401 会由 client 透明刷新 + 重试。
 */
export function HomePage() {
  const navigate = useNavigate()
  const logout = useAuthStore((s) => s.logout)
  const accessToken = useAuthStore((s) => s.accessToken)
  const [user, setUser] = useState<User | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setError(null)
    authApi
      .getMe()
      .then((u) => {
        if (active) setUser(u)
      })
      .catch((err) => {
        if (active) setError(ApiError.isApiError(err) ? err.message : '加载用户信息失败')
      })
    return () => {
      active = false
    }
  }, [accessToken])

  const onLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <main className="app-shell">
      <h1>drama-smith</h1>
      {error ? <p className="error">{error}</p> : null}
      <p>已登录,欢迎 {user ? user.username : '加载中…'}。</p>
      <p className="muted">
        文本模型配置:{user ? (user.text_model_configured ? '已配置' : '未配置') : '—'}
      </p>
      <button type="button" onClick={onLogout}>
        登出
      </button>
    </main>
  )
}
