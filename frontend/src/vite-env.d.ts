/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * API 基址。开发期留空 → 走 Vite dev 代理(/api、/ws 转发到后端);
   * 生产构建指向后端公网地址。见 frontend.md §10。
   */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
