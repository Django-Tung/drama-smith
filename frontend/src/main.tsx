import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from '@/App'
import '@/index.css'

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('挂载点 #root 未找到(index.html 缺少 <div id="root">)')
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
