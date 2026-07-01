import type { ApiErrorResponse, ApiSuccess, ListMeta } from '@/types'
import { getStoredAccessToken } from '@/utils/storage'

import { ApiError } from './errors'

/** API 基址:开发期留空 → 请求走 Vite 代理(/api、/ws);生产经 VITE_API_BASE 指向后端。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

type TokenGetter = () => string | null

/**
 * access token 取值器。默认读 localStorage;任务组 8 的 auth store 会经
 * `setAccessTokenGetter` 注入内存态单源,使 token 读取与存储解耦。
 */
let getAccessToken: TokenGetter = getStoredAccessToken

/** 覆盖 access token 取值器(供 Zustand auth store 注入内存态 token)。 */
export function setAccessTokenGetter(getter: TokenGetter): void {
  getAccessToken = getter
}

type RefreshHandler = () => Promise<string>

/**
 * 刷新处理器:用 refresh token 换新 access 并更新 store。由任务组 8 的 auth store
 * 经 `setRefreshHandler` 注入;client 不直接依赖 store,以避免循环依赖。
 */
let refreshHandler: RefreshHandler | null = null

/** 注册 / 注销 401 刷新处理器(auth store 注入)。 */
export function setRefreshHandler(handler: RefreshHandler | null): void {
  refreshHandler = handler
}

// 并发去重:多个 401 与守卫预刷新共享同一次刷新 Promise(frontend.md §7)。
let refreshInFlight: Promise<string> | null = null

/**
 * 触发一次(去重的)刷新,返回新 access token。
 *
 * - 无 handler → reject(`unauthenticated`),由调用方 / 守卫重定向登录;
 * - 刷新失败 → reject(store 侧已清空本地态,等同登出);
 * - 进行中 → 后续调用复用同一 Promise,避免并发重复打 /refresh。
 */
export function refreshSession(): Promise<string> {
  if (!refreshHandler) {
    return Promise.reject(
      new ApiError({ code: 'unauthenticated', message: 'Session expired', details: {} }, 401),
    )
  }
  if (refreshInFlight) return refreshInFlight
  refreshInFlight = refreshHandler().finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}

export interface RequestOptions {
  method?: string
  /** 请求体:JSON 可序列化对象/数组按 JSON 序列化;字符串原样透传;FormData 走 multipart。 */
  body?: object | string | FormData
  headers?: Record<string, string>
  /** URL 查询参数(值 undefined/null 跳过)。 */
  query?: Record<string, string | number | boolean | undefined | null>
  /** 显式覆盖 Authorization token(刷新重试时传新 access)。 */
  token?: string | null
  /**
   * 跳过 401 自动刷新。公开端点(register/login/refresh)的 401 是"凭证错误"
   * 而非"access 过期",必须置 true,否则会把"密码错误"误判为需要刷新。
   */
  skipAuthRefresh?: boolean
  signal?: AbortSignal
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const base = `${API_BASE}${path}`
  if (!query) return base
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) params.append(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${base}?${qs}` : base
}

function serializeBody(body: RequestOptions['body']): BodyInit | undefined {
  if (body == null) return undefined
  if (typeof body === 'string') return body
  if (typeof FormData !== 'undefined' && body instanceof FormData) return body
  return JSON.stringify(body)
}

async function doFetch(path: string, options: RequestOptions): Promise<Response> {
  const token = options.token !== undefined ? options.token : getAccessToken()
  const headers: Record<string, string> = { ...(options.headers ?? {}) }
  if (token) headers.Authorization = `Bearer ${token}`

  const hasBody = options.body != null
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData
  if (hasBody && !isFormData && headers['Content-Type'] == null) {
    headers['Content-Type'] = 'application/json'
  }

  return fetch(buildUrl(path, options.query), {
    method: options.method,
    headers,
    body: serializeBody(options.body),
    signal: options.signal,
  })
}

/**
 * 执行请求,并在 access 过期(401)时透明刷新 + 重试一次(frontend.md §7)。
 *
 * - 公开端点经 `skipAuthRefresh` 跳过(其 401 是凭证错误,不是 access 过期);
 * - 刷新成功 → 用新 access 重试一次,并置 `skipAuthRefresh` 防止循环;
 * - 刷新失败 / 无 handler → 返回原 401 响应(后续 readEnvelope 抛 `unauthenticated`)。
 */
async function fetchWithRefresh(path: string, options: RequestOptions): Promise<Response> {
  const res = await doFetch(path, options)
  if (res.status === 401 && !options.skipAuthRefresh && refreshHandler) {
    const newToken = await refreshSession()
    return doFetch(path, { ...options, token: newToken, skipAuthRefresh: true })
  }
  return res
}

/** 解包后端统一信封 `{ data, meta }`;失败抛 ApiError(携带 code/message/details)。 */
async function readEnvelope<T>(res: Response): Promise<{ data: T; meta: ListMeta | undefined }> {
  // 204 / 空 body(如 logout)→ 无 data。
  if (res.status === 204) return { data: null as T, meta: undefined }

  const text = await res.text()
  if (!text) return { data: null as T, meta: undefined }

  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new ApiError(
      { code: 'internal_error', message: 'Invalid JSON response from server', details: {} },
      res.status,
    )
  }

  if (!res.ok) {
    const errorBody = (parsed as ApiErrorResponse | null)?.error
    throw new ApiError(
      errorBody ?? {
        code: 'internal_error',
        message: res.statusText || 'Request failed',
        details: {},
      },
      res.status,
    )
  }

  const envelope = parsed as ApiSuccess<T>
  return { data: envelope.data, meta: envelope.meta }
}

/**
 * 发起请求并返回解包后的 `data`(frontend.md §6/§7)。含 401 自动刷新拦截。
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const res = await fetchWithRefresh(path, options)
  const { data } = await readEnvelope<T>(res)
  return data
}

/** 与 `request` 相同,但一并返回 `meta`(列表场景需要 total/page/page_size)。 */
export async function requestWithMeta<T>(
  path: string,
  options: RequestOptions = {},
): Promise<{ data: T; meta: ListMeta | undefined }> {
  const res = await fetchWithRefresh(path, options)
  return readEnvelope<T>(res)
}
