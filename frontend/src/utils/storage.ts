/**
 * Token 分层存储原语(design.md D9 / frontend.md §7)。
 *
 * - access  → localStorage(JS 读后附 `Authorization` 头;短时 15m);
 * - refresh → sessionStorage(随标签关闭失效;降低持久窃取风险)。
 *
 * 认证状态在任务组 8 由 Zustand store 接管为内存态单源,这里只提供
 * 持久化读写原语;store 与 `api/client.ts` 都复用本模块的键名。
 */

export const ACCESS_TOKEN_STORAGE_KEY = 'drama_smith.access_token'
export const REFRESH_TOKEN_STORAGE_KEY = 'drama_smith.refresh_token'

function safeGet(storage: Storage, key: string): string | null {
  try {
    return storage.getItem(key)
  } catch {
    return null
  }
}

function safeSet(storage: Storage, key: string, value: string): void {
  try {
    storage.setItem(key, value)
  } catch {
    // 隐私模式 / 存储被禁用时静默失败(token 仅存内存态亦可工作)。
  }
}

function safeRemove(storage: Storage, key: string): void {
  try {
    storage.removeItem(key)
  } catch {
    // 同上。
  }
}

export function getStoredAccessToken(): string | null {
  return safeGet(localStorage, ACCESS_TOKEN_STORAGE_KEY)
}

export function setStoredAccessToken(token: string): void {
  safeSet(localStorage, ACCESS_TOKEN_STORAGE_KEY, token)
}

export function getStoredRefreshToken(): string | null {
  return safeGet(sessionStorage, REFRESH_TOKEN_STORAGE_KEY)
}

export function setStoredRefreshToken(token: string): void {
  safeSet(sessionStorage, REFRESH_TOKEN_STORAGE_KEY, token)
}

/** 清除本地两类 token(登出时调用)。 */
export function clearStoredTokens(): void {
  safeRemove(localStorage, ACCESS_TOKEN_STORAGE_KEY)
  safeRemove(sessionStorage, REFRESH_TOKEN_STORAGE_KEY)
}
