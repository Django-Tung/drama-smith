/**
 * 认证域类型,对齐 user-auth spec 与 architecture.md §3.3 ①。
 * 字段命名与后端 pydantic 响应模型保持一致(snake_case)。
 */

/** 当前用户(GET /api/me)。 */
export interface User {
  id: number
  username: string
  /** 是否已配置文本模型(本期恒为 false,FR-C1 完成度占位)。 */
  text_model_configured: boolean
}

/** 访问令牌响应(POST /api/auth/refresh:仅换发新 access)。 */
export interface AccessTokenResponse {
  access_token: string
  /** 后端实际返回 "Bearer";前端 Authorization 头硬编码前缀,不依赖此值,故放宽为 string。 */
  token_type: string
}

/**
 * 注册 / 登录成功响应:同时签发 access + refresh
 * (spec「与登录同形」)。
 */
export interface TokenPairResponse extends AccessTokenResponse {
  refresh_token: string
}

/** 注册请求体。 */
export interface RegisterRequest {
  username: string
  password: string
}

/** 登录请求体。 */
export interface LoginRequest {
  username: string
  password: string
}

/** 刷新请求体:凭 refresh 换新 access。 */
export interface RefreshRequest {
  refresh_token: string
}
