# 架构详案(drama-smith)

> 版本:v0.1 · 状态:实施型契约 · 最近更新:2026-06-30
> **定位**:承接 [`system-architecture.md`](../architecture/system-architecture.md)(为什么这么选)与 [总纲](./README.md)(框架),本文落地**运行时架构与跨端契约**:拓扑、部署/进程模型、**前后端通信契约(REST 全量端点 + WebSocket 帧协议)**、**任务执行模型**、横切关注、目录结构。表结构见 [`database.md`](./database.md);后端/前端内部实现见 [`backend.md`](./backend.md)/[`frontend.md`](./frontend.md)。
> **已定默认**(总纲 §6):ORM = SQLAlchemy 2.0 async + Alembic;富媒体 = 本地磁盘 + `FileStore` 抽象;任务执行器 = 进程内 asyncio + 持久化恢复。

---

## 1. 运行时拓扑

```
                          ┌─────────────────────────────┐
                          │  浏览器(用户)               │
                          └──────────────┬──────────────┘
                                         │ HTTPS
┌────────────────────────────────────────▼─────────────────────────────────────┐
│  前端(独立工程,生产为静态产物)                                                │
│  React + TS + Vite  ·  路由/状态  ·  REST(fetch)+ WS 客户端  ·  token 分层存储  │
└────────────────────────────────────────┬─────────────────────────────────────┘
            REST(JSON,Authorization: Bearer)  +  WebSocket(/ws/tasks)
┌────────────────────────────────────────▼─────────────────────────────────────┐
│  后端(本仓库)· 单体 FastAPI 进程(uvicorn)                                    │
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │ api 层:REST 路由 + /ws/tasks  ·  依赖注入(JWT 校验·用户注入·隔离过滤)       │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │ 服务/编排:graphs(LangGraph 分析图)· analysis 节点 · 任务执行器(asyncio)    │ │
│ ├──────────────────────────────────────────────────────────────────────────┤ │
│ │ core:llm 接缝(litellm + 视频适配器)· config · crypto(信封加密)· pydantic  │ │
│ │ db :SQLAlchemy 2.0 async ORM + 会话         storage:FileStore(本地磁盘)   │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
└───────┬──────────────────────────────────────┬─────────────────────────┬─────┘
        │ asyncmy                              │ FileStore               │ HTTP
┌───────▼───────────┐          ┌───────────────▼────────────┐   ┌─────────▼──────────┐
│   MySQL 8          │          │  富媒体(本地磁盘卷)         │   │  LLM 供应商          │
│ 用户·配置·任务·     │          │  图/视频/成片(对象化存储键)  │   │  文本/图片/视频       │
│ 产物元数据·分镜     │          │  (后续可切 MinIO/S3)        │   │  (用户 BYOK 凭证)    │
└────────────────────┘          └────────────────────────────┘   └────────────────────┘
```

**组件职责**:前端仅渲染与编排用户操作;后端是唯一的业务与鉴权权威;MySQL 承结构化数据与元数据,富媒体卷承二进制(路径/键落 MySQL),LLM 供应商经 `core/llm` 单一接缝访问。**前端绝不直连 MySQL 或 LLM**。

---

## 2. 部署与进程模型(本期)

| 维度 | 本期模型 | 说明 / 演进 |
|------|----------|-------------|
| 后端进程 | **单体**:1 个 uvicorn 进程,内置 asyncio 任务执行器 | 单实例足以承接本期量级;多实例时任务执行需外移到消息队列(见 §7) |
| Worker | uvicorn 单 worker(或 `--workers 1`);任务在进程内 asyncio | 多 worker 会使进程内任务执行器失配(任务落某 worker 内存),故本期固定单 worker |
| 前端 | 独立工程;开发用 Vite dev server,生产构建为静态产物,由 nginx(或后端静态托管)分发 | 开发期前端经 Vite 代理 `/api`、`/ws` 到后端,避开 CORS 复杂度 |
| 数据库 | MySQL 8 单实例,utf8mb4 | 连接池(SQLAlchemy async pool) |
| 富媒体 | 本地磁盘挂载卷,`FileStore` 抽象统一读写 | 迁移对象存储时仅换 `FileStore` 实现 |
| 凭证密钥 | JWT 签名密钥、MEK 经环境变量(`.env`)注入 | 生产接 KMS(预留) |

**进程重启语义**:任务执行器在内存,进程重启会丢失在跑协程。启动时扫描 `running` 任务→置为 `interrupted`(可重试),由用户重试/单步重做,不自动续跑(本期不上 LangGraph checkpointer,见 §4.4)。

---

## 3. 前后端通信契约

### 3.1 通信方式总览

| 方式 | 用途 | 鉴权 |
|------|------|------|
| **REST/JSON** | 全部 CRUD、发起任务、**任务轮询基线**、导出下载 | `Authorization: Bearer <access_token>`(除 register/login/refresh) |
| **WebSocket `/ws/tasks`** | 任务页前台打开时**实时**进度推送(增强通道) | 连接时携带 token(query 或子协议) |
| CORS | 后端放行配置的前端源 | — |

> 双通道共享同一任务记录(落 MySQL);前端择一,WS 不可达时回退 REST 轮询(承接 [总纲 §6](./README.md)、[analysis.md §4.5](../requirements/features/analysis.md))。

### 3.2 统一约定

- **路径前缀**:所有业务接口 `/api/*`;WebSocket `/ws/tasks`。
- **响应包装(成功)**:`{ "data": <payload>, "meta": { ... } }`;列表带 `meta: { total, page, page_size }`。
- **错误格式**:`{ "error": { "code": "<MACHINE_CODE>", "message": "<人类可读>", "details": {...} } }`,HTTP 状态码与 `code` 对齐(见 §5.2)。
- **ID**:资源标识用整数(`:id`),路径里的 `:dramaId`/`:epId`/`:cid` 同理。
- **鉴权默认开**:除 `register`/`login`/`refresh` 外,所有端点强制 Bearer token;越权访问他人资源一律 **404**(不泄露存在性)。
- **幂等/并发**:写操作必要时带 `If-Match`/版本号(剧本/分镜编辑,见 database.md 版本字段)。

### 3.3 REST 端点清单(全量)

> 字段级契约随变更细化;此处定**资源域、方法、路径、鉴权、关联需求**。均归属当前用户、强制隔离。

**① 认证与当前用户**([user-auth.md](../requirements/features/user-auth.md))

| 方法 | 路径 | 鉴权 | 说明 | 需求 |
|------|------|------|------|------|
| POST | `/api/auth/register` | 公开 | 用户名+密码注册 | FR-U1 |
| POST | `/api/auth/login` | 公开 | 登录→签发 access + refresh | FR-U1 |
| POST | `/api/auth/logout` | Bearer | 吊销 refresh、客户端弃 access | FR-U4 |
| POST | `/api/auth/refresh` | refresh | 凭 refresh 换新 access | FR-U4 |
| GET | `/api/me` | Bearer | 当前用户 + 配置完成度(是否已配文本模型) | FR-U2 / FR-C1 |

**② 模型配置(BYOK)**([ai-config.md](../requirements/features/ai-config.md))

| 方法 | 路径 | 鉴权 | 说明 | 需求 |
|------|------|------|------|------|
| GET/POST | `/api/me/models` | Bearer | 列表 / 新增(用途 text/image/video);Key 加密落库 | FR-C2/C4 |
| PUT/DELETE | `/api/me/models/:id` | Bearer | 改(切换不动 Key)/ 删(active 删除规则见 ai-config §2.2) | FR-C2 |
| POST | `/api/me/models/:id/activate` | Bearer | 置为该用途当前生效 | FR-C2 |
| POST | `/api/me/models/:id/test` | Bearer | 连通性自检(零成本,不真生成) | FR-C3 |

**③ 公共角色库**([character-library.md](../requirements/features/character-library.md))

| 方法 | 路径 | 鉴权 | 说明 | 需求 |
|------|------|------|------|------|
| GET/POST | `/api/me/characters` | Bearer | 库角色列表(检索/筛选)/ 新建 | FR-L1/L2/L6 |
| GET/PUT/DELETE | `/api/me/characters/:id` | Bearer | 详情 / 改 / 删(不级联已引入副本) | FR-L1 |
| POST | `/api/me/characters/:id/image` | Bearer | 图片模型**生成**形象图(需图片模型) | FR-L4 |
| POST | `/api/me/characters/:id/image/upload` | Bearer | 手动**上传**(≤1MB,超限压缩) | FR-L4 |
| POST | `/api/me/characters/:id/clone-to-episode/:epId` | Bearer | 库角色**引入**为该剧剧本角色(复制) | FR-L5 |

**④ 剧 / 剧集 / 剧本**([analysis.md](../requirements/features/analysis.md))

| 方法 | 路径 | 鉴权 | 说明 | 需求 |
|------|------|------|------|------|
| POST/GET | `/api/dramas` | Bearer | 建剧 / 列表(重命名/删除) | FR-A1 |
| POST/GET | `/api/dramas/:dramaId/episodes` | Bearer | 建剧集(含画幅/风格基调)/ 列表 | FR-A1/§4.4 |
| GET/PUT/DELETE | `/api/episodes/:id` | Bearer | 详情 / 改(排序/画幅/风格)/ 删 | FR-A1 |
| PUT | `/api/episodes/:id/script` | Bearer | 写入/更新剧本(保留版本) | FR-A2 |
| POST | `/api/episodes/:id/script/optimize` | Bearer | AI 优化(异步任务,返回比对/版本) | FR-A3 |

**⑤ 剧集角色(含库双向流转)**

| 方法 | 路径 | 鉴权 | 说明 | 需求 |
|------|------|------|------|------|
| GET/POST | `/api/episodes/:id/characters` | Bearer | 剧集角色列表 / 新建(`fromLibraryId` 可引入库角色) | FR-A4/L5 |
| GET/PUT/DELETE | `/api/episodes/:id/characters/:cid` | Bearer | 改(含形象参考)/ 删 | FR-A4 |
| POST | `/api/episodes/:id/characters/:cid/promote-to-library` | Bearer | 剧集角色**加入库**(抽取复制) | FR-L3 |
| POST | `/api/episodes/:id/characters/:cid/image` | Bearer | 角色形象参考(上传或生成) | FR-A4/§4.2 |

**⑥ 分析拆解 / 分镜**

| 方法 | 路径 | 鉴权 | 说明 | 需求 |
|------|------|------|------|------|
| POST | `/api/episodes/:id/analyze` | Bearer | 发起文本拆解(异步任务) | FR-A5 |
| GET | `/api/episodes/:id/analysis` | Bearer | 取拆解结果(角色/情节线/冲突/节奏) | FR-A5 |
| GET | `/api/episodes/:id/shots` | Bearer | 分镜清单 | FR-A6 |
| PATCH | `/api/shots/:id` | Bearer | 编辑单镜(描述/景别/时长/角色/对白) | FR-A6 |
| POST | `/api/shots/:id/split` | Bearer | 拆分一镜为多镜 | FR-A6 |
| POST | `/api/shots/:id/merge` | Bearer | 与相邻镜合并 | FR-A6 |

**⑦ 视觉素材 / 视频 / 合并 / 导出**

| 方法 | 路径 | 鉴权 | 说明 | 需求 |
|------|------|------|------|------|
| POST | `/api/shots/:id/media` | Bearer | 单镜素材:上传或图片生成(多候选) | FR-A7 |
| POST | `/api/shots/:id/video` | Bearer | 逐镜视频生成/重生成(多候选,需视频模型) | FR-A8 |
| POST | `/api/episodes/:id/render` | Bearer | 合并成片(取各镜选定视频,硬切) | FR-A9 |
| POST | `/api/episodes/:id/export` | Bearer | 导出(mp4 + 台本 + 角色卡) | FR-A10 |
| GET | `/api/episodes/:id/stream` | Bearer | REST 流式进度(WS 不可达时回退) | §3.1 |

**⑧ 任务中心**([analysis.md §4.5](../requirements/features/analysis.md))

| 方法 | 路径 | 鉴权 | 说明 | 需求 |
|------|------|------|------|------|
| GET | `/api/tasks` | Bearer | 跨剧集任务列表(状态/剧集/时间过滤,分页) | FR-A11 |
| GET | `/api/tasks/:id` | Bearer | 任务详情(进度/阶段/错误/产物) | FR-A11 |
| POST | `/api/tasks/:id/cancel` | Bearer | 取消 running(已落地产物保留) | FR-A11 |
| POST | `/api/tasks/:id/retry` | Bearer | 重试 failed/canceled(复用输入) | FR-A11 |

### 3.4 WebSocket 帧协议(`/ws/tasks`)

**连接**:`ws(s)://<host>/ws/tasks?token=<access_token>`(或子协议携带);连接即视为订阅当前用户的任务事件。token 失效→服务端发 `error` 后关闭,前端走刷新或重登。

**帧结构**(JSON 文本帧,服务端→客户端):

```jsonc
{ "type": "task.progress", "task_id": 123, "ts": "2026-06-30T12:00:00Z",
  "payload": { "status": "running", "progress": 42, "stage": "rendering_shot", "episode_id": 7 } }
```

| `type`(S→C) | 触发 | payload 摘要 |
|--------------|------|--------------|
| `task.progress` | 状态/进度/阶段变化 | `status`,`progress`(0–100),`stage`,`episode_id` |
| `task.completed` | 进入 `succeeded` | `result_refs`(产物引用),`finished_at` |
| `task.failed` | 进入 `failed` | `error:{code,message}` |
| `pong` | 回应 `ping` | — |
| `error` | 协议/鉴权错误 | `error:{code,message}` |

| `type`(C→S) | 用途 |
|-------------|------|
| `ping` | 心跳(保活、探活) |
| `subscribe` / `unsubscribe` | 可选:按 `task_id` 精订阅,减少噪声 |

**重连与回退**:前端指数退避重连;重连失败或页面后台→切换 REST 轮询 `GET /api/tasks/:id`(间隔随任务阶段动态,如 2–5s)。两条通道读同一任务记录,进度以服务端记录为准、幂等覆盖前端本地态。

---

## 4. 任务执行模型(本期核心基础设施)

> 任务 = 流水线中**耗时不确定、需异步等待**的步骤(优化 / 拆解 / 图片 / 视频 / 合并)。统一抽象、持久化、用户隔离(承接 [analysis.md §4.5/§5.4](../requirements/features/analysis.md)、[总纲 §6](./README.md))。

### 4.1 任务记录与状态机

```
          提交校验通过              执行器拉起            正常完成
 pending ─────────► running ─────────► succeeded
   │                   │  ▲
   │用户取消           │  │进程重启
   ▼                   │  │扫描恢复
 canceled ◄────────────┘  │
                          ▼
        failed ◄──── 抛错/供应商错误        interrupted(可重试)
```

| 字段 | 说明 |
|------|------|
| `id`,`user_id`,`episode_id` | 归属(用户隔离 + 跳转剧集) |
| `type` | `optimize`/`analyze`/`image`/`video`/`render`(/`promote` 若入队) |
| `status` | `pending`/`running`/`succeeded`/`failed`/`canceled`/`interrupted` |
| `progress`(0–100),`stage` | 进度百分比 + 当前阶段(供 UI 展示) |
| `input_snapshot` | 发起时的输入与**模型配置快照**(JSON) |
| `output_refs` | 产物引用(媒体/分镜/分析 id,JSON) |
| `error` | `{code,message,details}`(失败时) |
| `trigger` | `single`/`batch` |
| `created_at`/`started_at`/`finished_at` | 时间线 |

### 4.2 执行器架构(进程内 asyncio)

```
REST 发起 ──► 校验(配额/门禁/输入) ──► 落 pending 记录 ──► 入队(asyncio.Queue/信号量)
                                                                  │
                                            执行器协程池(按用户限流)▼
                              拉起任务协程 → running → 经 core/llm 调用 → 写产物 → succeeded/failed
                                                                  │
                                              进度回调 ──► 更新记录 ──► 推 /ws/tasks(订阅者)
```

- **并发控制**:每用户并发上限(默认 3–5,可配);超限任务留 `pending` 排队;全局协程上限按配置。批量生成前给**成本预估与确认**(BYOK)。
- **进度来源**:LangGraph 图节点的流式事件 / 适配器的轮询结果 → 归一化为 `(progress, stage)` 写记录并广播。
- **配置快照**:任务发起时把当前生效模型配置快照入 `input_snapshot`;运行中用户改配置**不影响**在途调用(承接 [ai-config §7.4](../requirements/features/ai-config.md))。

### 4.3 取消、重试、单步重做

- **取消**:`running` 可取消 → 协作式 `asyncio.Task.cancel()`;**已落地产物(已完成的图/视频)保留**,未完成终止,置 `canceled`。
- **重试**:`failed`/`canceled`/`interrupted` 可单条重试,复用 `input_snapshot`,产出追加为候选。
- **单步重做**:单张图 / 单镜 / 单视频独立重生成(走对应 `media`/`video` 端点,各自落任务或即时任务),不必整条重跑。

### 4.4 重启恢复

进程启动时扫描 `status=running` 的任务 → 置为 `interrupted`(带 `error.code=restart_interrupted`)→ 任务页提示可重试。**不自动续跑**:本期拆解/生成耗时在分钟级、可单步重做,任务记录 + 重试已满足「回来继续看已落地产物」;长流程断点续跑(需 LangGraph checkpointer 复用 MySQL)留待 §7。

### 4.5 进度双通道(再确认)

- **REST 轮询(基线)**:`GET /api/tasks`、`/api/tasks/:id`——始终可用,断线/后台友好。
- **WebSocket(增强)**:任务页前台订阅 `/ws/tasks`,免高频轮询。
- 共享同一任务记录(§4.1);前端择一,以服务端记录为唯一事实源。

---

## 5. 横切关注

### 5.1 鉴权与多租户隔离(双层把关)

- **JWT 校验依赖**:FastAPI 依赖注入解析 `Authorization`、验签(HS256)、取 `sub`(user_id)注入请求上下文;失败 401。
- **资源归属校验**:任何按 `:id` 访问的资源先 `WHERE id=:id AND user_id=:current_user`;不存在或不归属→**404**(不暴露存在)。
- **查询强制带 `user_id`**:列表/聚合类端点一律按当前用户过滤(NFR-7)。详见 [`database.md`](./database.md) §5 与 [`backend.md`](./backend.md) 的仓储层。
- **登录防爆破**:失败计数按账号维度,连续 5 次锁 15 分钟(`users.locked_until`),不按 IP(承接 [user-auth §5](../requirements/features/user-auth.md))。

### 5.2 错误处理与供应商错误映射

- 统一异常 → §3.2 错误格式;常见 `code`:`unauthenticated`/`forbidden`/`not_found`/`validation_error`/`rate_limited`/`provider_error`/`model_not_configured`/`quota_exceeded`/`internal_error`。
- **凭证失效检测**:LLM 返回 401/403/鉴权失败 → 标记该 `model_configs.status=invalid`(承接 [FR-C5](../requirements/features/ai-config.md)),任务 `failed` 并提示重新配置。
- 429/超时:按用途降级或有限重试(承接 [FR-C6](../requirements/features/ai-config.md))。

### 5.3 配置管理

- `pydantic-settings` 读 `.env`;分层:代码默认 → `.env` → 环境变量。敏感项(JWT 密钥、MEK、DB 密码、存储根路径)**不入库、不入日志、不入 OpenAPI schema**。
- 前端构建期注入 `VITE_API_BASE` 等(运行时由后端 CORS 放行)。

### 5.4 日志与可观测性

- 标准库 `logging` + rich handler;结构化关键字段 `user_id`/`task_id`/`episode_id`/`provider`。
- **脱敏**:API Key、token、密文一律不打日志;展示脱敏(`sk-…ab12`)。
- 后续可升 structlog / 接链路追踪(本期最小化)。

### 5.5 CORS 与安全头

- 后端 CORS 放行配置的前端源(开发期可放宽到 `localhost:5173`)。
- 收敛 XSS 面:不使用 `httpOnly` Cookie 存 token,故配合输出转义、限制第三方脚本、CSP(承接 [user-auth §5](../requirements/features/user-auth.md))。

### 5.6 富媒体访问

- 上传/生成 → `FileStore.save()` 得对象键 → 元数据落 `media` 表(见 [`database.md`](./database.md))。
- **访问鉴权**:前端不直读磁盘路径;经鉴权端点代理或**短期签名 URL** 下发,防止越权读他人媒体(配合 §5.1)。
- 上传约束:库角色/角色形象图 ≤ 1MB、超限压缩(承接 [FR-L4](../requirements/features/character-library.md));视频体积大,设用户配额与清理策略。

---

## 6. 目录结构总览

### 6.1 后端(本仓库)— 承接 [`system-architecture.md`](../architecture/system-architecture.md) §3,标注本期范围

```
drama-smith/
├── pyproject.toml · uv.lock · .env.example · alembic.ini
├── src/drama_smith/
│   ├── main.py               # FastAPI 入口(挂 REST + /ws/tasks、CORS、启动恢复)
│   ├── api/                  # 接口层:auth/users/models/characters/dramas/episodes
│   │                         #         shots/media/video/render/export/tasks + ws/tasks
│   ├── core/                 # config(pydantic-settings)· crypto(信封加密)· logging · security(JWT)
│   ├── llm/                  # 供应商无关接缝:litellm 文本/图片 + 视频自定义适配器(统一接口)
│   ├── graphs/               # LangGraph 图定义(本期:analysis 图)
│   ├── analysis/             # 分析图节点 + 提示工程(拆解/分镜/一致性)
│   ├── tasks/                # 任务执行器(asyncio)· 状态机 · 恢复 · 进度广播
│   ├── storage/              # FileStore 抽象 + 本地磁盘实现
│   ├── db/                   # SQLAlchemy 模型 · 异步会话/引擎 · 仓储层(强制 user_id 过滤)
│   └── migrations/           # Alembic(env.py + versions/)
├── tests/                    # pytest(+cov):单元/集成(含临时 MySQL 或 testcontainers)
├── docs/ · openspec/
└── (generation/ simulation/  # 推迟,仅保留结构位,本期不实现)
```

### 6.2 前端(独立工程)— 结构详见 [`frontend.md`](./frontend.md)

```
drama-smith-web/        # 独立工程(命名待定)
├── package.json · vite.config.ts · tsconfig.json
└── src/  routes/  components/  hooks/(useWebSocket/useApi)  stores/  api/(REST+WS 客户端)  types/
```

---

## 7. 待定 / 后续

- **多实例部署**时,任务执行器需外移到消息队列(Celery/RQ/ARQ + Redis/Broker),`tasks/` 执行接口预留以便替换。
- **富媒体对象存储**:本地磁盘 → MinIO/S3,仅换 `FileStore` 实现,元数据表不变。
- **LangGraph checkpointer**:是否复用 MySQL 支持长流程断点续跑(本期靠任务记录 + 重试,见 §4.4)。
- 前端**工程仓库位置/命名**(architecture §6 遗留)。
- WebSocket 的**子协议鉴权** vs query token 的最终选择(安全权衡)。
