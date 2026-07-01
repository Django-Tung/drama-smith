import {
  Clapperboard,
  Library,
  ListTodo,
  LogOut,
  PanelLeft,
  PanelLeftClose,
  Settings,
  User as UserIcon,
} from 'lucide-react'
import { useEffect, type ComponentType } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { authApi } from '@/api/endpoints'
import { ThemeToggle } from '@/components/ThemeToggle'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/utils/cn'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

interface NavItemDef {
  to: string
  label: string
  icon: ComponentType<{ className?: string }>
}

const NAV: NavItemDef[] = [
  { to: '/dramas', label: '我的剧库', icon: Clapperboard },
  { to: '/library', label: '角色库', icon: Library },
  { to: '/tasks', label: '任务中心', icon: ListTodo },
  { to: '/settings', label: '设置', icon: Settings },
]

/**
 * 受保护区应用骨架(frontend.md §3):侧栏导航 + 顶栏(主题/用户菜单)+ 内容 Outlet。
 * 挂载时拉取 /api/me 写入 auth.user(access 过期由 client 透明刷新);登出复用 auth.logout。
 */
export function AppShell() {
  const navigate = useNavigate()
  const setUser = useAuthStore((s) => s.setUser)
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const collapsed = useUiStore((s) => s.sidebarCollapsed)
  const toggleSidebar = useUiStore((s) => s.toggleSidebar)

  useEffect(() => {
    authApi
      .getMe()
      .then(setUser)
      .catch(() => {
        /* 进 AppShell 前已由 RequireAuth 保证有效会话;此处失败(刷新也败)忽略,顶栏显示占位。 */
      })
  }, [setUser])

  const onLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
        {/* 侧栏 */}
        <aside
          className={cn(
            'flex shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground transition-[width] duration-200',
            collapsed ? 'w-16' : 'w-60',
          )}
        >
          <div className="flex h-14 items-center gap-2 border-b px-3">
            <NavLink
              to="/dramas"
              className="flex items-center gap-2 overflow-hidden"
              title="drama-smith"
            >
              <Clapperboard className="size-5 shrink-0 text-sidebar-primary" />
              {!collapsed && (
                <span className="truncate font-serif text-lg font-semibold">drama-smith</span>
              )}
            </NavLink>
            {!collapsed && (
              <Button
                variant="ghost"
                size="icon"
                className="ml-auto size-8"
                onClick={toggleSidebar}
                aria-label="折叠侧栏"
                title="折叠侧栏"
              >
                <PanelLeftClose />
              </Button>
            )}
          </div>

          <nav className="flex flex-1 flex-col gap-1 p-2">
            {NAV.map((item) => (
              <SidebarLink key={item.to} item={item} collapsed={collapsed} />
            ))}
          </nav>

          {collapsed && (
            <div className="border-t p-2">
              <Button
                variant="ghost"
                size="icon"
                className="w-full"
                onClick={toggleSidebar}
                aria-label="展开侧栏"
                title="展开侧栏"
              >
                <PanelLeft />
              </Button>
            </div>
          )}
        </aside>

        {/* 主区 */}
        <div className="flex flex-1 flex-col overflow-hidden">
          <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-background px-4">
            <div className="flex-1" />
            <ThemeToggle />
            <Separator orientation="vertical" className="h-6" />
            {/* 用户菜单 */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="gap-2">
                  <UserIcon className="size-4" />
                  <span className="max-w-[8rem] truncate">{user?.username ?? '加载中…'}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <DropdownMenuLabel className="truncate">{user?.username ?? '—'}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" onClick={onLogout}>
                  <LogOut /> 登出
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </header>

          <main className="flex-1 overflow-y-auto p-6">
            <Outlet />
          </main>
        </div>
      </div>
    </TooltipProvider>
  )
}

/** 侧栏导航项:展开显示图标+文字;折叠仅图标 + Tooltip 提示。 */
function SidebarLink({ item, collapsed }: { item: NavItemDef; collapsed: boolean }) {
  const Icon = item.icon
  const link = (
    <NavLink
      to={item.to}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
          collapsed && 'justify-center px-2',
          isActive
            ? 'bg-sidebar-accent text-sidebar-accent-foreground'
            : 'text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground',
        )
      }
    >
      <Icon className="size-4 shrink-0" />
      {!collapsed && <span className="truncate">{item.label}</span>}
    </NavLink>
  )

  if (!collapsed) return link
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">{item.label}</TooltipContent>
    </Tooltip>
  )
}
