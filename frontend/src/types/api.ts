/**
 * 后端统一通信契约的类型对齐(architecture.md §3.2 / design.md D7)。
 *
 * 成功响应:`{ data, meta }`;错误响应:`{ error: { code, message, details } }`。
 * 前端 `request<T>` 解包 `data` 返回;列表场景额外读 `meta`。
 */

/** 列表分页元信息(architecture.md §3.2:列表带 meta.total/page/page_size)。 */
export interface ListMeta {
  total: number
  page: number
  page_size: number
}

/** 成功响应信封。meta 在非列表响应中可能缺省。 */
export interface ApiSuccess<T> {
  data: T
  meta?: ListMeta
}

/**
 * 机器可读错误码,与后端 core/errors.py + architecture.md §5.2 对齐。
 *
 * 显式列举本期落地的 code,同时以 `string` 兜底:后端新增 code 时不致
 * 破坏前端编译(未知 code 仍可被消费,运行时按字符串处理)。
 */
export type ErrorCode =
  | 'unauthenticated' // 401 缺少/无效/过期凭证
  | 'forbidden' // 403
  | 'not_found' // 404 不存在或越权(不泄露存在性)
  | 'validation_error' // 422 请求校验失败
  | 'conflict' // 409 资源冲突(如用户名占用)
  | 'locked' // 423 账号锁定
  | 'rate_limited'
  | 'provider_error'
  | 'model_not_configured'
  | 'quota_exceeded'
  | 'internal_error'
  | 'error'
  | (string & {}) // 兜底:未列举的 code

/** 错误体(`error` 字段的形状)。 */
export interface ApiErrorBody {
  code: ErrorCode
  message: string
  details?: Record<string, unknown>
}

/** 错误响应信封。 */
export interface ApiErrorResponse {
  error: ApiErrorBody
}
