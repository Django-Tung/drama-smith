import { Moon, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { applyTheme } from '@/utils/applyTheme'
import { useUiStore } from '@/stores/ui'

/**
 * 主题切换按钮,顺带承担「把主题落到 <html>」的全局副作用:
 * - 订阅 ui.theme,变化时重新 applyTheme(增删 .dark + color-scheme)。
 * - system 模式下监听系统偏好变化并跟随。
 * 点击按「当前生效态」在 light/dark 间切换(忽略 system,变为显式明暗)。
 * 挂在 AppShell 顶栏,随受保护页常驻;公开页(/login、/register)由 index.html
 * 内联脚本保证首屏正确。
 */
export function ThemeToggle() {
  const theme = useUiStore((s) => s.theme)
  const setTheme = useUiStore((s) => s.setTheme)
  const [resolvedDark, setResolvedDark] = useState(false)

  useEffect(() => {
    const compute = () => {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      const dark = theme === 'dark' || (theme === 'system' && prefersDark)
      applyTheme(theme)
      setResolvedDark(dark)
    }
    compute()
    if (theme !== 'system') return
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    mql.addEventListener('change', compute)
    return () => mql.removeEventListener('change', compute)
  }, [theme])

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(resolvedDark ? 'light' : 'dark')}
      aria-label={resolvedDark ? '切换到浅色' : '切换到深色'}
      title={resolvedDark ? '浅色模式' : '深色模式'}
    >
      {resolvedDark ? <Sun /> : <Moon />}
    </Button>
  )
}
