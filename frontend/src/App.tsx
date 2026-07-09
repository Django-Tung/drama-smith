import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from '@/components/AppShell'
import { RequireAuth } from '@/components/RequireAuth'
import { RequireSetup } from '@/components/RequireSetup'
import { DramasPage } from '@/routes/DramasPage'
import { EpisodePage } from '@/routes/EpisodePage'
import { LibraryPage } from '@/routes/LibraryPage'
import { LoginPage } from '@/routes/LoginPage'
import { RegisterPage } from '@/routes/RegisterPage'
import { SettingsPage } from '@/routes/SettingsPage'
import { SetupPage } from '@/routes/SetupPage'
import { TasksPage } from '@/routes/TasksPage'

/**
 * 根路由(frontend.md §3 + design D11):
 * - /login、/register:公开;
 * - /setup:受 `RequireAuth` 保护(会话 + user),但绕过文本配置门禁 —— 向导;
 * - /:受 `RequireAuth` + `RequireSetup`(未配文本模型 → 重定向 /setup)→ `AppShell`
 *   + 嵌套路由;index 重定向到 /dramas。
 */
export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          path="/setup"
          element={
            <RequireAuth>
              <SetupPage />
            </RequireAuth>
          }
        />
        <Route
          path="/"
          element={
            <RequireAuth>
              <RequireSetup>
                <AppShell />
              </RequireSetup>
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/dramas" replace />} />
          <Route path="dramas" element={<DramasPage />} />
          <Route path="episodes/:episodeId" element={<EpisodePage />} />
          <Route path="library" element={<LibraryPage />} />
          <Route path="tasks" element={<TasksPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/dramas" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
