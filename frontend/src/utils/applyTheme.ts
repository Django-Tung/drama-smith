import type { Theme } from '@/stores/ui'

/**
 * 依据主题 + 系统偏好,在 <html> 上增删 `dark` 类并设置原生 `color-scheme`
 * (后者让滚动条/原生控件跟随)。
 *
 * 纯副作用函数(无 React 依赖),供 ThemeToggle 调用。
 * 与 index.html 的内联无闪烁脚本保持同一逻辑(脚本无法 import,故各自维护)。
 *
 * 注:不放在 `src/lib/`,因根 .gitignore 的 `lib/` 规则会忽略之。
 */
export function applyTheme(theme: Theme): void {
  if (typeof window === 'undefined') return
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
  const isDark = theme === 'dark' || (theme === 'system' && prefersDark)
  const root = document.documentElement
  root.classList.toggle('dark', isDark)
  root.style.colorScheme = isDark ? 'dark' : 'light'
}
