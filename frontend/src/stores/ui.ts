import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Theme = 'light' | 'dark' | 'system'

interface UiState {
  /** 主题:light / dark / system(跟随系统偏好)。system 为默认初始值。 */
  theme: Theme
  /** 侧栏折叠态(持久化)。 */
  sidebarCollapsed: boolean
  setTheme: (theme: Theme) => void
  setSidebarCollapsed: (collapsed: boolean) => void
  toggleSidebar: () => void
}

/**
 * 纯客户端 UI 态(frontend.md §5):主题 + 侧栏。
 * 用 persist 中间件存 localStorage(key 与 index.html 无闪烁脚本读取的一致)。
 */
export const useUiStore = create<UiState>()(
  persist(
    (set, get) => ({
      theme: 'system',
      sidebarCollapsed: false,
      setTheme: (theme) => set({ theme }),
      setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),
      toggleSidebar: () => set({ sidebarCollapsed: !get().sidebarCollapsed }),
    }),
    {
      name: 'drama-smith.ui',
      partialize: (s) => ({ theme: s.theme, sidebarCollapsed: s.sidebarCollapsed }),
    },
  ),
)
