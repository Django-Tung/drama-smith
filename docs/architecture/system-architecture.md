# 架构设计(drama-smith)

> 版本:v0.7 · 状态:初稿 · 最近更新:2026-06-30
> **v0.7 变更**:① 决策反转——由「非 monorepo(后端独仓)」改为 **monorepo**:前后端同仓,后端在 `backend/`(src layout 包 `drama_smith`)、前端在 `frontend/`(React + Vite),各自独立工具链;§1、§3、§4.4 同步修订;② §6「前端仓库位置/命名」待定项**已定**(并入 monorepo `frontend/`)。落地理由见 [`tech-solution/architecture.md`](../tech-solution/architecture.md) D10。
> **v0.6 变更**:① §4.3 补**任务进度双通道**——长任务持久化为记录,状态经 REST 轮询(基线)+ WebSocket `/ws/tasks` 实时推送(自 analysis.md §4.5);② §6「分析长任务流式通道(SSE vs WebSocket)」待定项**已定**:轮询 + WS、不用 SSE。
> **v0.5 变更**:① 新增 §4.6 **认证/令牌实现**(argon2id、JWT(HS256)、刷新令牌、客户端分层存储,自 user-auth.md §5 下沉);② §4.5 API Key 加密方案补全自包含;③ §6 增「分析长任务流式通道选型」待定项。
> **v0.4 变更**:① 持久化层补 **MySQL**(技术栈表 + 目录结构 + §4.5 持久化决策);② `core/llm` 接缝补充:视频等 litellm 覆盖不全者以**自定义适配器**承接(NFR-2);③ 目录结构标注本期范围(仅落地 analysis,生成/模拟推迟)。
> **v0.3 变更**:① 前后端通信改用 **WebSocket**(双向);② 前端确认 **TypeScript**;③ **非 monorepo**——本仓库(drama-smith)仅含后端,前端为独立项目;④ 补充 LangGraph 通俗说明。
> (v0.2:由单包 CLI 改为前后端分离 Web 应用)
> 本文档沉淀项目级架构决策。


## 1. 总览

drama-smith 是前后端分离的 Web 应用,**monorepo**(前后端同仓,后端 `backend/` + 前端 `frontend/`):

- **后端**(Python 3.12+ · FastAPI + LangGraph):暴露 WebSocket / HTTP 接口;**LangGraph 作为三大子系统的编排引擎**,把"生成 / 分析 / 模拟"实现为可检查点、可恢复的有状态图。
- **前端**(`frontend/` · Node 22 + React + TypeScript):用户界面,经 **WebSocket** 与后端实时交互,渲染剧本、角色卡、分析结果、模拟过程。
- **LLM 层**:供应商无关的接缝 `core/llm`(文本/图片经 litellm,视频等覆盖不全者以自定义适配器承接),藏在 LangGraph 节点之下,子系统不直接耦合任何厂商。
- **持久化层**:**MySQL**——承载用户、(加密的)模型配置、分析任务及其结构化产物/分镜/富媒体,按用户隔离;ORM/迁移候选 SQLAlchemy 2.0 + Alembic(见 §4.5、§6)。

```
┌──────────────────────────┐         WebSocket(双向)         ┌────────────────────────────────────────┐
│   前端(frontend/)        │  ───────────────────────────►   │            后端(backend/)              │
│   Node 22 + React (TS)    │  ◄───────────────────────────   │            Python 3.12+                 │
│  ┌──────────────────────┐ │        JSON 文本帧 / 流式       │  ┌───────────────────────────────────┐  │
│  │ pages 生成/分析/模拟   │ │                                 │  │  FastAPI(接口层)                  │  │
│  │ WebSocket 客户端      │ │                                 │  │  /ws/{generation,simulation} 等    │  │
│  │ components           │ │                                 │  ├───────────────────────────────────┤  │
│  └──────────────────────┘ │                                 │  │  LangGraph(编排层)                │  │
└──────────────────────────┘                                 │  │  生成图 / 分析图 / 多角色模拟图     │  │
                                                              │  ├───────────────────────────────────┤  │
                                                              │  │  core:llm 接缝 / config / models  │  │
                                                              │  └─────────────────┬─────────────────┘  │
                                                              └────────────────────┼────────────────────┘
                                                                                   │
                                                                            ┌──────▼──────┐
                                                                            │  LLM 供应商  │ OpenAI / Anthropic / 本地
                                                                            └─────────────┘
```

## 2. 技术栈(决策)

### 2.1 前端(`frontend/`)

| 维度 | 选型 | 理由(摘要) |
|------|------|-------------|
| 运行时 | Node.js 22 (LTS) | 现代长期支持版,生态兼容性好 |
| 框架 | **React + TypeScript** | 组件化 UI + 类型安全(已确认) |
| 构建 | Vite | 极速冷启 / HMR,React 事实标准 |
| 包管理 | npm(或 pnpm) | Node 默认 / pnpm 更省空间 |
| 实时通信 | 原生 WebSocket(封装为 hook) | 双向,承载生成流式与模拟实时回合 |
| 代码规范 | ESLint + Prettier | 前端 lint/format |

### 2.2 后端(`backend/`)

| 维度 | 选型 | 理由(摘要) |
|------|------|-------------|
| 运行时 | Python 3.12+ | 现代类型标注、性能、稳定 |
| 依赖/构建 | uv | 单工具、高速、可复现锁文件 |
| Web 框架 | FastAPI | 原生 pydantic、自动 OpenAPI、async、WebSocket 友好 |
| 编排引擎 | LangGraph | 把三大子系统建成有状态图;天然契合"多角色模拟"等多 actor 流程 |
| 领域模型/配置 | pydantic v2 + pydantic-settings | 校验、序列化、请求/响应模型、环境配置 |
| LLM 访问 | litellm + `core/llm` 自定义适配器(视频等) | 文本/图片经 litellm;视频等覆盖不全者在 `core/llm` 内补适配器,供应商无关、易切换 |
| 日志 | 标准库 logging(rich handler) | 零新增依赖;后续可升 structlog |
| 持久化 | **MySQL** | 关系型;承载用户、模型配置、分析任务与产物(用户隔离,NFR-7) |
| ORM / 迁移 | SQLAlchemy 2.0 + Alembic(候选) | 候选栈,最终选型随变更定(见 §6) |
| 质量 | ruff + pytest(+cov) + mypy | lint/format/测试/类型检查 |

### 2.3 前后端协作

| 维度 | 选型 | 理由 |
|------|------|------|
| 通信 | **WebSocket**(双向):承载生成的流式增量、模拟的实时回合,客户端可中途输入 | 双向 + 流式,一套满足生成与模拟 |
| 辅助 | REST/JSON 仅用于无状态简单请求(如分析报告、健康检查) | 不必所有交互都建连 |
| 消息格式 | JSON 文本帧 | 调试方便、类型可描述 |
| 跨域 | 后端 CORS 放行前端源 | 跨域对接必需 |

## 3. 目录结构(monorepo)

> monorepo:前后端同仓。后端结构在 `backend/`,前端在 `frontend/`(结构见 [`tech-solution/frontend.md`](../tech-solution/frontend.md) §1)。

```
drama-smith/                      # monorepo(前后端同仓)
├── backend/                      # 后端(FastAPI + LangGraph)
│   ├── pyproject.toml · uv.lock · .env.example
│   └── src/drama_smith/
│       ├── __init__.py
│       ├── main.py               # FastAPI 应用入口(挂 REST + /ws/tasks、CORS、启动恢复)
│       ├── api/                  # 接口层:REST 端点 + WebSocket /ws/tasks
│       ├── core/                 # config / logging / security / crypto / llm 接缝(含视频自定义适配器)/ pydantic 模型
│       ├── db/                   # SQLAlchemy ORM 模型 + 异步会话/引擎 + 仓储(强制 user_id 过滤)
│       ├── migrations/           # Alembic 迁移
│       ├── graphs/               # LangGraph 定义(本期仅分析图;生成/模拟图推迟)
│       ├── analysis/             # 分析图节点与提示工程(本期核心)
│       ├── generation/           # 生成图节点与提示工程(推迟,保留结构位)
│       └── simulation/           # 多角色模拟图(推迟,保留结构位)
│   └── tests/
├── frontend/                     # 前端(React + TS + Vite),结构见 tech-solution/frontend.md
├── docs/
└── openspec/
```

## 4. 关键设计决策

### 4.1 LangGraph 作为编排引擎

**LangGraph 是什么**:LangGraph(LangChain 团队出品)用来搭建"有状态、多步骤 LLM 应用"。它把复杂任务拆成若干**节点**(一次逻辑/LLM 调用),节点间用**边**连成一张**图**,数据在共享**状态(State)** 里流转,支持条件分支、循环、检查点(可暂停/续跑)和流式输出。

**三大子系统各是一张图**:
- **生成图**:主题/大纲 → 规划节点 → 逐场景生成 → 对白 → 组装 → 输出(可检查点、可续写)。
- **分析图**:剧本 → 抽取角色/情节点 → 分析冲突/节奏 → 综合报告。
- **模拟图**:多 actor(每个角色一个 agent)+ 导演 agent,按轮次推进(对应 LangGraph 的多 agent 模式)。

FastAPI 仅作薄接口层:接 WebSocket → 调对应图 → 把图输出流式推回前端。

### 4.2 供应商无关 LLM 接缝(保留 NFR-2)
模型访问仍只经 `drama_smith.core.llm` 暴露。LangGraph 节点消费由该层构造的聊天模型(底层 litellm)。`generation`/`analysis`/`simulation` **绝不**直接导入 litellm 或任何供应商 SDK。文本/图片类经 litellm 直连;**视频类(litellm 覆盖最弱、且多为异步 submit/poll)在 `core/llm` 内以自定义适配器承接**,对外仍统一接口——切换供应商只改配置、不破子系统(NFR-2)。

### 4.3 WebSocket 实时通信
生成、模拟这类长耗时/需中途输入的任务走 **WebSocket** 双向连接:后端把 LangGraph 的流式输出实时推给前端,前端也能在模拟中随时注入输入(如让某角色回应)。一次性、无状态请求(分析报告、健康检查)用 REST。后端配置 CORS 放行前端源。

**任务进度(分析流水线 · 双通道)**:分析流水线的长任务(剧本优化 / 拆解 / 图片 / 视频 / 合并)**持久化为任务记录**,状态回传走**双通道**——REST 轮询(`GET /api/tasks`、`GET /api/tasks/:id`)为**可靠基线**(断线 / 关页面可继续看),前台打开任务页时经 WebSocket(`/ws/tasks`)**订阅**实时进度推送、断线自动回退轮询;两条通道共享同一任务记录,前端择一即可。需求见 [`analysis.md`](../requirements/features/analysis.md) §4.5。

### 4.4 monorepo(前后端同仓)
后端在 `backend/`(src layout 包 `drama_smith`),前端在 `frontend/`(React + Vite),**同属一个仓库**,各自独立工具链(Python/uv 与 Node/npm),通过 WebSocket/REST 接口契约对接。接口契约(端点、消息格式)统一在 [`tech-solution/architecture.md`](../tech-solution/architecture.md) 维护。

> v0.7 反转此前 v0.3 的「非 monorepo」决策:改为前后端同仓以统一文档/CI/契约管理,落地理由见 [`tech-solution/architecture.md`](../tech-solution/architecture.md) D10。

### 4.5 持久化:MySQL(本期)
用户、模型配置(含**加密 API Key**:信封加密——主密钥(MEK)经环境变量/KMS 注入、不入库,数据密钥以 AES-256-GCM 加密、密文与 IV 落库;需求见 [`features/ai-config.md`](../requirements/features/ai-config.md) §6)、分析任务及其结构化产物、分镜与富媒体引用,**均落 MySQL,按用户隔离**(NFR-7);前端不经 DB,经接口读写。ORM/迁移候选为 SQLAlchemy 2.0 + Alembic,最终随变更定。LangGraph 分析图的检查点(checkpointer)是否复用 MySQL 做长流程断点续跑,待定(§6)。

### 4.6 认证与令牌实现

对应安全需求见 [`features/user-auth.md`](../requirements/features/user-auth.md) §5;此处记**技术选型**:

- **密码哈希**:argon2id 优先、bcrypt 次选(加盐、单向、不可逆)。
- **访问令牌**:JWT(HS256 对称签名,签名密钥来自环境变量);claims 含 `sub`(用户 ID)、`username`、`iat`、`exp`;短时有效(默认 15 分钟)、无服务端状态。
- **刷新令牌**:不透明随机串,服务端仅存哈希(关联用户与过期时间)、**可吊销**,默认 7 天;因访问令牌短时过期,登出无需维护 JWT 黑名单。
- **客户端令牌存储(分层)**:访问令牌 → `localStorage`(前端 JS 读取后附到请求头);刷新令牌 → 内存 / `sessionStorage`(随标签页关闭即失效);**不采用 `httpOnly` Cookie**,相应收敛 XSS 面(输出转义、限制第三方脚本、CSP)。
- **登录防爆破阈值**:默认连续 5 次失败锁定 15 分钟、仅按账号维度,时间窗后自动解锁(本期无邮箱,不支持邮件解锁)。

## 5. 数据流(高层)

1. 前端建立 WebSocket 连接(如 `/ws/simulation`)。
2. FastAPI 接收消息,校验后调用对应 LangGraph 图执行。
3. 图节点经 `core/llm` 调用 LLM,产出中间态与最终结果。
4. 图输出经 WebSocket 流式推回前端;模拟场景下前端可中途发消息影响流程。

> 各子系统图的具体节点、状态、提示工程待各自功能变更细化。

## 6. 待定问题

- ~~LangGraph 之下的模型用 litellm 还是 LangChain 原生模型工厂?~~ → **已定(2026-06-26)**:文本/图片经 litellm,视频等经 `core/llm` 自定义适配器(NFR-2)。
- **MySQL 之上的配套**:ORM/迁移最终选型(SQLAlchemy 2.0 + Alembic 为候选),与 [`system-requirements.md`](../requirements/system-requirements.md) §6 对齐。
- 是否需要 LangGraph 的**持久化检查点**(checkpointer,可复用 MySQL)以支持长流程断点续跑?
- WebSocket 端点与消息格式的**接口契约**初稿(端点路径、帧结构)?
- ~~**分析长任务的流式通道**选型(SSE vs WebSocket)?~~ → **已定(2026-06-30)**:长任务**持久化为记录**,状态经 **REST 轮询(基线)+ WebSocket `/ws/tasks` 实时推送**回传,**不采用 SSE**(断线回退轮询)。见 §4.3 与 [`analysis.md`](../requirements/features/analysis.md) §4.5。
- ~~前端独立项目的**仓库位置/命名**?~~ → **已定(2026-06-30)**:并入 monorepo,前端为 `frontend/` 目录(见 §4.4)。

## 7. 与既有规划的关系(重要)

本次架构调整**取代**了 `setup-project-foundation` 变更里的若干早期决策:
- CLI(typer)入口 → 改为 **FastAPI 后端 + 独立 React 前端**。
- 单包布局(根级 src 包)→ 保留为**后端仓库结构**(新增 `api/`、`graphs/`,去掉 CLI)。
- 编排方式(原 litellm 直调)→ 改为 **LangGraph 编排,litellm 退居为模型层接缝**。

因此 `openspec/changes/setup-project-foundation/` 的 proposal/design/specs/tasks **已与新架构不一致**;按既定选择,目前**暂不同步**,待前端细节确认后再统一修订。
