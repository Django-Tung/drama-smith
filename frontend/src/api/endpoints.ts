import type {
  AccessTokenResponse,
  LoginRequest,
  RefreshRequest,
  RegisterRequest,
  TokenPairResponse,
  User,
} from '@/types'

import { request } from './client'

/**
 * 认证与当前用户端点(architecture.md §3.3 ①)。
 * 每个方法对齐一个 REST 路径;返回类型取自 `@/types`(与后端 pydantic 契约对齐)。
 *
 * 公开端点(register/login/refresh)一律 `skipAuthRefresh: true`:其 401 是"凭证
 * 错误"而非"access 过期",不可触发自动刷新(否则会把"密码错误"误判为需刷新)。
 */
export const authApi = {
  /** 注册:校验用户名/密码、argon2id 落库、签发 access + refresh,201。 */
  register(body: RegisterRequest): Promise<TokenPairResponse> {
    return request<TokenPairResponse>('/api/auth/register', {
      method: 'POST',
      body,
      skipAuthRefresh: true,
    })
  },

  /** 登录:校验密码、防爆破计数、成功签发 access + refresh。 */
  login(body: LoginRequest): Promise<TokenPairResponse> {
    return request<TokenPairResponse>('/api/auth/login', {
      method: 'POST',
      body,
      skipAuthRefresh: true,
    })
  },

  /** 刷新:凭 refresh 换新 access(spec:仅返回新 access;令牌轮换为可选增强)。 */
  refresh(body: RefreshRequest): Promise<AccessTokenResponse> {
    return request<AccessTokenResponse>('/api/auth/refresh', {
      method: 'POST',
      body,
      skipAuthRefresh: true,
    })
  },

  /** 登出:吊销当前 refresh(Bearer 鉴权 + body 指定要吊销的 refresh)。 */
  async logout(body: RefreshRequest): Promise<void> {
    await request<unknown>('/api/auth/logout', { method: 'POST', body })
  },

  /** 当前用户信息 + 文本模型配置完成度(GET /api/me)。 */
  getMe(): Promise<User> {
    return request<User>('/api/me')
  },
}
