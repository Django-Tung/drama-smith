import { create } from 'zustand'

import { setAccessTokenGetter, setRefreshHandler } from '@/api/client'
import { authApi } from '@/api/endpoints'
import { ApiError } from '@/api/errors'
import {
  clearStoredTokens,
  getStoredAccessToken,
  getStoredRefreshToken,
  setStoredAccessToken,
  setStoredRefreshToken,
} from '@/utils/storage'
import type { LoginRequest, TokenPairResponse, User } from '@/types'

interface AuthState {
  /** access token:内存单源,镜像写入 localStorage(design.md D9)。 */
  accessToken: string | null
  /** refresh token:内存 + sessionStorage(随标签关闭失效)。 */
  refreshToken: string | null
  /** 当前用户(内存态;App 启动 / 登录后由 getMe 填充)。 */
  user: User | null
  setSession: (tokens: TokenPairResponse, user?: User) => void
  setAccessToken: (token: string) => void
  setUser: (user: User) => void
  clear: () => void
  /** 登录:调 /api/auth/login 并落地令牌;失败抛 ApiError。 */
  login: (credentials: LoginRequest) => Promise<TokenPairResponse>
  /** 登出:吊销 refresh(失败不阻塞)+ 清本地态。 */
  logout: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: getStoredAccessToken(),
  refreshToken: getStoredRefreshToken(),
  user: null,

  setSession(tokens, user) {
    setStoredAccessToken(tokens.access_token)
    setStoredRefreshToken(tokens.refresh_token)
    set({
      accessToken: tokens.access_token,
      refreshToken: tokens.refresh_token,
      user: user ?? null,
    })
  },

  setAccessToken(token) {
    setStoredAccessToken(token)
    set({ accessToken: token })
  },

  setUser(user) {
    set({ user })
  },

  clear() {
    clearStoredTokens()
    set({ accessToken: null, refreshToken: null, user: null })
  },

  async login(credentials) {
    const tokens = await authApi.login(credentials)
    get().setSession(tokens)
    return tokens
  },

  async logout() {
    const { refreshToken } = get()
    if (refreshToken) {
      try {
        await authApi.logout({ refresh_token: refreshToken })
      } catch {
        // 吊销失败(access 过期且刷新也失败)不阻塞本地登出。
      }
    }
    get().clear()
  },
}))

// 让 api/client 读 access token 时取内存单源(刷新成功后立即可见,且与 localStorage 一致)。
setAccessTokenGetter(() => useAuthStore.getState().accessToken)

/**
 * 用 refresh token 换新 access 并更新 store(供 api/client 经 `setRefreshHandler` 调用)。
 *
 * 去重由 api/client 的共享 Promise 负责;本函数只做:取 refresh → 调 /refresh → 更新
 * store → 返回新 access。失败时清空本地态(刷新不可用即等同登出)并向上抛出。
 */
async function refreshAccessToken(): Promise<string> {
  const refreshToken = useAuthStore.getState().refreshToken
  if (!refreshToken) {
    throw new ApiError(
      { code: 'unauthenticated', message: 'No refresh token available', details: {} },
      401,
    )
  }
  try {
    const { access_token } = await authApi.refresh({ refresh_token: refreshToken })
    useAuthStore.getState().setAccessToken(access_token)
    return access_token
  } catch (error) {
    useAuthStore.getState().clear()
    throw error
  }
}

setRefreshHandler(refreshAccessToken)
