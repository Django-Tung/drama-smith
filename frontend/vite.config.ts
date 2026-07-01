import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 开发期 dev 代理的后端源(后端默认起在 :8000,见 backend/src/drama_smith/main.py)。
// 生产构建不走 dev 代理,API 基址由 VITE_API_BASE 在运行时决定。
const BACKEND_URL = 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // Vite 默认端口;后端 CORS 默认放行 http://localhost:5173(见 backend core/config.py)。
    port: 5173,
    proxy: {
      // REST:统一前缀 /api(architecture.md §3.2)。
      '/api': { target: BACKEND_URL, changeOrigin: true },
      // WebSocket:/ws/tasks(architecture.md §3.4);ws:true 透传连接升级。
      '/ws': { target: BACKEND_URL, changeOrigin: true, ws: true },
    },
  },
})
