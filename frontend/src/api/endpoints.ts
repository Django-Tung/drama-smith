import type {
  AccessTokenResponse,
  LoginRequest,
  ModelConfig,
  ModelConfigCreate,
  ModelConfigUpdate,
  ModelPurpose,
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

/**
 * BYOK 模型配置端点(architecture.md §3.3,setup-byok-config)。
 * 对齐 `/api/me/models/...`;响应仅脱敏 key(`api_key_masked`),明文 key 只在
 * create / update 请求体中,经 `request` 走标准 401 自动刷新拦截。
 */
export const modelsApi = {
  /** 列出我的模型配置(仅脱敏 key);`purpose` 可选过滤。 */
  list(purpose?: ModelPurpose): Promise<ModelConfig[]> {
    return request<ModelConfig[]>('/api/me/models', { query: { purpose } })
  },

  /** 获取单条配置(越权访问 → 404,不泄露存在性)。 */
  get(id: number): Promise<ModelConfig> {
    return request<ModelConfig>(`/api/me/models/${id}`)
  },

  /** 新建:白名单校验 → 信封加密落库 → 首条自动 active,201。 */
  create(body: ModelConfigCreate): Promise<ModelConfig> {
    return request<ModelConfig>('/api/me/models', { method: 'POST', body })
  },

  /** 按 model_fields_set 语义更新(仅传显式字段;缺省 key 不动加密列 D8)。 */
  update(id: number, body: ModelConfigUpdate): Promise<ModelConfig> {
    return request<ModelConfig>(`/api/me/models/${id}`, { method: 'PUT', body })
  },

  /** 删除;删 active 且同 purpose 有兄弟须指定继任 `newActiveId`,否则 409 invalid_state。 */
  async delete(id: number, newActiveId?: number): Promise<void> {
    await request<unknown>(`/api/me/models/${id}`, {
      method: 'DELETE',
      query: { new_active_id: newActiveId },
    })
  },

  /** 激活:单事务内翻转为当前 purpose 的 active(其余翻 0,D3)。 */
  activate(id: number): Promise<ModelConfig> {
    return request<ModelConfig>(`/api/me/models/${id}/activate`, { method: 'POST' })
  },

  /** 零成本自检(GET /models,不真生成);鉴权失败(401/403)置 invalid + 502。 */
  test(id: number): Promise<ModelConfig> {
    return request<ModelConfig>(`/api/me/models/${id}/test`, { method: 'POST' })
  },
}
