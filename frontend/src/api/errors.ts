import type { ApiErrorBody, ErrorCode } from '@/types'

/**
 * REST 客户端统一抛出的错误(`api/client.ts` 解析失败响应后构造)。
 * 携带后端的 `code` / `message` / `details` 与 HTTP 状态(frontend.md §6)。
 */
export class ApiError extends Error {
  readonly code: ErrorCode
  readonly status: number
  readonly details: Record<string, unknown>

  constructor(body: ApiErrorBody, status: number) {
    super(body.message)
    this.name = 'ApiError'
    this.code = body.code
    this.status = status
    this.details = body.details ?? {}
  }

  static isApiError(error: unknown): error is ApiError {
    return error instanceof ApiError
  }
}
