# 前端技术方案(drama-smith)

> 版本:v0.1 · 状态:实施型 · 最近更新:2026-06-30
> **定位**:承接 [`architecture.md`](./architecture.md)(通信契约)与 [`backend.md`](./backend.md)(后端实现),本文落地**前端(`frontend/`)的工程结构与实现**:React 工程、路由与页面、状态管理、REST/WebSocket 客户端、token 分层存储与自动刷新、多候选与流式交互、表单与上传、构建部署。前端绝不直连 MySQL 或 LLM,一切经后端契约。
> **默认决策**:Node.js 22 + React + TypeScript + Vite;状态 = TanStack Query(服务端)+ Zustand(客户端);原生 WebSocket 封装为 hook;ESLint + Prettier。
> **仓库**:monorepo 前端目录 `frontend/`(前后端同仓,承接 [总纲](./README.md) 与 [`architecture.md`](./architecture.md) D10);其技术方案归本目录统一维护。

---

## 1. 工程结构

```
frontend/
├── package.json · vite.config.ts · tsconfig.json · .eslintrc · .prettierrc
├── index.html
└── src/
    ├── main.tsx                 # 挂载 + Provider(QueryClient/WS/Auth)
    ├── App.tsx                  # 根路由 + 路由守卫
    ├── routes/                  # 页面(§4):auth/onboarding/settings/dramas/episode/library/tasks
    ├── components/              # 通用组件(布局、表单、MediaPicker、CandidateList、ProgressBadge…)
    ├── features/                # 按域组织逻辑:drama/episode/shot/media/video/render/task/character/model
    │   └── <domain>/  api.ts  hooks.ts  components/  types.ts
    ├── api/
    │   ├── client.ts            # fetch 封装:基址、鉴权头、统一错误、401 刷新拦截(§7)
    │   └── endpoints.ts         # 按资源域的端点函数(对齐 architecture §3.3)
    ├── realtime/
    │   ├── ws.ts                # WebSocket 连接管理:连接/重连/心跳/订阅
    │   └── useTaskProgress.ts   # hook:订阅任务进度,断线回退轮询(§8)
    ├── stores/
    │   ├── auth.ts              # Zustand:token 内存态 + 持久化分层(§7)
    │   └── ui.ts                # 主题/侧栏等纯客户端状态
    ├── hooks/                   # useCurrentUser / useModelGate / useFileUpload …
    ├── types/                   # 与后端契约对齐的 TS 类型(请求/响应/WS 帧/领域模型)
    └── utils/                   # format / mask / cost-estimate …
```

**组织约定**:按 `features/<domain>` 聚合"该域的 API + hook + 组件 + 类型",`routes/` 只负责页面装配与路由;跨域通用件进 `components/`。

---

## 2. 技术栈与工具链

| 维度 | 选型 | 理由 |
|------|------|------|
| 运行时 | Node.js 22 (LTS) | 现代长期支持 |
| 框架 | React 18 + TypeScript | 组件化 + 类型安全(NFR-4) |
| 构建 | Vite | 极速 HMR、事实标准 |
| 包管理 | npm(或 pnpm) | pnpm 更省空间 |
| 路由 | React Router(v6+,数据路由) | 嵌套路由 + 守卫 |
| 服务端状态 | **TanStack Query (React Query)** | 缓存、轮询、失效、乐观更新;天然契合任务轮询基线 |
| 客户端状态 | **Zustand** | 轻量,存 token/UI 态 |
| 表单 | React Hook Form + Zod | 受控 + 类型安全校验(对齐后端 pydantic 约束) |
| 样式 | Tailwind CSS(建议)或 CSS Modules | 快速一致;样式方案可调 |
| HTTP | 原生 `fetch` 封装 | 无额外依赖 |
| 实时 | 原生 `WebSocket` 封装为 hook | 双向任务进度(§8) |
| 规范 | ESLint + Prettier + TypeScript(`strict`) | NFR-3/4 |

---

## 3. 路由与守卫

| 路径 | 页面 | 鉴权 | 需求 |
|------|------|------|------|
| `/login` · `/register` | 登录/注册 | 公开 | FR-U1 |
| `/onboarding` | 首次配置向导(必配文本模型) | 登录 + 未配文本 | FR-C1 |
| `/settings` | 模型配置 + 个人信息 | 登录 | FR-C2 |
| `/dramas` · `/dramas/:dramaId` | 我的剧库 / 剧集列表 | 登录 | FR-A1 |
| `/episodes/:id` | 剧集工作台(子路由:剧本/角色/分镜台/成片) | 登录 | FR-A2~A10 |
| `/library` | 公共角色库 | 登录 | FR-L |
| `/tasks` | 任务中心(跨剧集汇总) | 登录 | FR-A11 |

**守卫**:
- `RequireAuth`:无 access 且刷新失败→重定向 `/login`。
- `RequireTextModel`:`GET /api/me` 显示未配文本→重定向 `/onboarding`([FR-C1](../requirements/features/ai-config.md));图片/视频未配→对应入口禁用并提示去设置(`useModelGate`)。

---

## 4. 页面与旅程实现要点

- **剧集工作台**(`/episodes/:id`,核心):以分步/Tab 呈现流水线——剧本输入(AI 优化比对/版本回退)→ 发起拆解 → 分镜编辑台 → 素材 → 逐镜视频 → 合并 → 导出;各耗时步骤内联进度 + 可跳任务页。
- **分镜编辑台**:列表(拖拽排序)+ 行内编辑(描述/景别/时长/对白/出场角色)+ 拆分/合并;编辑后客户端预校验 3–15s([analysis §5.1](../requirements/features/analysis.md)),提交 `PATCH`/`split`/`merge`。
- **多候选交互**(`CandidateList`):图片/视频候选以缩略图网格展示,标记 `selected`;支持「再生成一张」(单步重做)、选用切换;生成前弹成本预估与确认(BYOK)。
- **角色库 ↔ 剧集**:`promote-to-library` / `clone-to-episode` 两个入口,复制语义(前端提示"独立副本、不联动")。
- **任务页**:列表(状态/剧集/时间过滤)+ 进度条 + 错误 + 「跳回工作台产物位置」;前台用 WS、后台/断线用轮询(§8)。

---

## 5. 状态管理(分层)

| 类型 | 工具 | 用途 |
|------|------|------|
| 服务端数据(剧/剧集/分镜/媒体/任务/配置) | TanStack Query | 缓存 + 失效 + 轮询(`refetchInterval`) + 乐观更新(编辑分镜) |
| 任务实时进度 | `useTaskProgress`(WS,§8) | 写入 Query 缓存,与轮询同源 |
| 鉴权/Token | Zustand(`auth`) | access/refresh 内存态 + 分层持久化(§7) |
| 纯 UI 态 | Zustand(`ui`) | 侧栏/主题等 |

**约定**:变更后用 `queryClient.invalidateQueries({ queryKey })` 失效相关域(如选用某候选后失效该镜媒体);避免手写同步。

---

## 6. REST 客户端(`api/client.ts`)

```ts
// 伪码示意
async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...authHeader(), ...opts.headers },
  });
  if (res.status === 401 && await tryRefresh()) return request(path, opts);  // 刷新后重试(§7)
  const body = await res.json();
  if (!res.ok) throw new ApiError(body.error);                                // {code,message,details}
  return body.data as T;
}
```

- 统一解包 `{data, meta}`、统一抛 `ApiError`(携带 `code/message/details`,对齐 [architecture §3.2](./architecture.md))。
- 端点函数(`endpoints.ts`)按资源域分组,返回类型用 `types/` 中的 TS 类型(与后端 pydantic 对齐)。
- 分页:透传 `meta.total/page/page_size`。

---

## 7. Token 分层存储与自动刷新

承接 [user-auth §5](../requirements/features/user-auth.md) 与 [architecture §4.6](../architecture/system-architecture.md):

| 令牌 | 存储 | 说明 |
|------|------|------|
| access token | `localStorage` | JS 读取后附 `Authorization` 头;短时(15m) |
| refresh token | 内存(Zustand)/ `sessionStorage` | 随标签关闭失效;降低持久窃取风险 |

- **自动刷新拦截**:`request` 遇 401 → 调 `/api/auth/refresh`(用刷新令牌)→ 换新 access → 重试原请求(并发去重:多个 401 共享一次刷新 Promise)。
- **登出**:调 `/api/logout`(吊销刷新)→ 清除本地两类 token → 重定向 `/login`。
- **收敛 XSS 面**:不用 `httpOnly` Cookie 存 token;配合输出转义、CSP、限制第三方脚本。

---

## 8. WebSocket 客户端与双通道回退(`realtime/`)

**连接(`ws.ts`)**:`ws(s)://<host>/ws/tasks?token=<access>`(token 失效→服务端 `error` 关闭→前端走刷新/重登)。

**hook(`useTaskProgress.ts`)**:

```ts
// 伪码示意:订阅任务进度,断线自动回退轮询
function useTaskProgress(taskId: number) {
  // 1) WS 通道:收到 task.progress/completed/failed → 写 Query 缓存
  useWsSubscription({ type: 'subscribe', task_id: taskId }, (frame) => updateTaskCache(frame));
  // 2) 回退:WS 未连上/后台 → TanStack Query 轮询
  useQuery({
    queryKey: ['task', taskId],
    queryFn: () => api.getTask(taskId),
    enabled: !wsConnected || document.hidden,
    refetchInterval: (q) => pollInterval(q.state.data),   // 按阶段动态 2–5s;终态停
  });
}
```

- **重连**:指数退避(如 1s/2s/4s… 上限),重连成功切回 WS、停轮询。
- **同源**:WS 与轮询都写同一 Query 缓存键 `['task', id]`,以后到为准、幂等覆盖([architecture §3.4](./architecture.md))。
- **任务页**:批量订阅用户任务事件(`subscribe` 不带 id 或带列表),避免为每条任务各开连接。

---

## 9. 表单校验与上传

- **校验**:React Hook Form + Zod,规则与后端对齐——用户名 3–32、密码 ≥8 含字母+数字([FR-U1](../requirements/features/user-auth.md));前端即时反馈,后端为最终权威。
- **图片上传**:前端预检类型/大小(≤1MB),超限可前端预压缩或交后端压缩([FR-L4](../requirements/features/character-library.md));`multipart/form-data` 上传。
- **成本预估**:批量图片/视频生成前,依据任务类型 + 数量给估算并要求确认(BYOK)。

---

## 10. 构建与部署

- **开发**:Vite dev server(`localhost:5173`),经 `vite.config.ts` 代理 `/api`、`/ws` → 后端,避开 CORS。
- **生产**:`vite build` 产出静态产物,由 nginx(或后端静态托管)分发;运行时 API 基址经 `VITE_API_BASE` 注入。
- **环境**:`.env.development` / `.env.production`;敏感配置不进前端构建产物(前端只持有用户运行时 token,无任何服务端密钥)。

---

## 11. 待定 / 后续

- 样式方案最终选型(Tailwind vs CSS Modules)。
- 状态管理若趋复杂,评估引入路由级数据加载(React Router loaders)与 Query 的分工。
- 离线/弱网下的任务进度缓存策略。
- 视频大文件前端预览与播放(流式/HLS)方案。
