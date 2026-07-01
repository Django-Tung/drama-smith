import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from '@/components/AppShell'
import { RequireAuth } from '@/components/RequireAuth'
import { DramasPage } from '@/routes/DramasPage'
import { LibraryPage } from '@/routes/LibraryPage'
import { LoginPage } from '@/routes/LoginPage'
import { RegisterPage } from '@/routes/RegisterPage'
import { SettingsPage } from '@/routes/SettingsPage'
import { TasksPage } from '@/routes/TasksPage'

/**
 * 根路由(frontend.md §3)。
 * - /login、/register:公开;
 * - /:受 `RequireAuth` 保护 → `AppShell`(侧栏/顶栏)+ 嵌套路由(Outlet);
 *   index 重定向到 /dramas(登录后落地页)。
 */
export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/dramas" replace />} />
          <Route path="dramas" element={<DramasPage />} />
          <Route path="library" element={<LibraryPage />} />
          <Route path="tasks" element={<TasksPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/dramas" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
