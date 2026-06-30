## Context

drama-smith 已决定采用前后端分离的 Web 架构(FastAPI 后端 + 独立 React 前端 + MySQL),完整技术方案沉淀于 [`docs/tech-solution/`](../../../docs/tech-solution/)(总纲 / 架构详案 / 数据库设计 / 后端 / 前端),需求侧见 [`docs/requirements/features/user-auth.md`](../../../docs/requirements/features/user-auth.md)(FR-U)。

**当前状态**:仓库无后端/前端代码;`openspec/` 此前为空,旧的 `setup-project-foundation`(CLI 单包)已失效。本变更是新架构的第一个落地切片(里程碑 M0),只做「项目地基 + 用户与认证」,为后续里程碑(BYOK 配置、结构化分析、分镜视频流水线等)提供可运行的骨架与 `user_id` 隔离范式。

**约束**:macOS 优先;后端 Python 3.12+、前端 Node 22;敏感配置(JWT 密钥、DB DSN、MEK)经 `.env` 注入、不入库/日志;多租户隔离(NFR-7)、认证与会话安全(NFR-6)为硬约束。

## Goals / Non-Goals

**Goals:**

- 可一条命令安装/运行/测试的后端骨架(uv + FastAPI + ruff/mypy/pytest)。
- MySQL 持久化层(SQLAlchemy 2.0 async + Alembic),初始迁移建 `users`、`refresh_tokens`。
- 完整认证流程:注册 / 登录 / 登出 / 刷新 / `GET /api/me`;argon2id + JWT(HS256)+ 可吊销刷新令牌 + 账号维度防爆破。
- 多租户隔离的仓储范式(强制 `user_id` 过滤),后续业务表直接复用。
- 可运行的前端骨架(Vite + React + TS),含登录/注册页、路由守卫、带 401 自动刷新的 REST 客户端、token 分层存储。

**Non-Goals:**

- AI 服务配置(BYOK,FR-C)、结构化分析与分镜视频流水线(FR-A)、公共角色库(FR-L)、任务中心(FR-A11)、剧本生成/模拟(FR-G/FR-S)——均属后续里程碑。
- 富媒体存储(`FileStore`)与任务执行器——本期不需要(`GET /api/me` 的 `text_model_configured` 恒为 `false`)。
- LangGraph、`core/llm` 接缝、WebSocket `/ws/tasks`——本期不引入。
- 邮箱验证 / 邀请码 / 邮件解锁(本期不开邮箱)。
- 多实例部署、JWT 黑名单、checkpointer。

## Decisions

**D1 后端单体 FastAPI + uv + 分层 + 依赖注入。** 单实例足以承接 M0;`api/core/db/migrations` 分层,依赖方向只向下([`backend.md §1`](../../../docs/tech-solution/backend.md))。*替代*:Flask(异步/WS 弱)、Litestar(生态小)。选 FastAPI 因 async、pydantic 原生、自动 OpenAPI、WS 友好(为后续 `/ws/tasks` 铺路)。

**D2 MySQL + SQLAlchemy 2.0 async(asyncmy)+ Alembic。** async 与 FastAPI 一致;迁移可控、可回溯;字段对齐 [`database.md §3.1`](../../../docs/tech-solution/database.md)。*替代*:SQLModel(薄但与 pydantic v2 耦合、迁移生态弱)、Tortoise ORM(生态小)、同步驱动(浪费 async)。`users`/`refresh_tokens` 为后续所有业务表的 `user_id` 关联源头。

**D3 密码 argon2id(argon2-cffi)。** 加盐、抗 GPU/侧信道,优于 bcrypt。可降级 bcrypt 兼容,但默认 argon2id。

**D4 JWT(HS256,15min,无状态)+ 不透明可吊销刷新令牌(7d,仅存哈希)。** 访问令牌短时无状态、无需查库;刷新令牌服务端可吊销以支持登出/失效。*替代*:纯无状态 JWT(无法即时登出)、`httpOnly` Cookie 存 token(本期显式不采用,以收敛 CSRF 面并允许前端 JS 读 token 附头——见 [`architecture §4.6`](../../../docs/tech-solution/architecture.md))。

**D5 登录防爆破仅按账号维度(5 次 / 15min,自动解锁)。** 不按 IP(避免 NAT/共享 IP 误伤)、不用指数退避、不引入验证码(本期无邮箱)。落库字段 `failed_login_count`、`locked_until`。

**D6 多租户隔离在仓储层强制 `user_id`。** 仓储方法签名一律带 `user_id`,查询自动 `WHERE id=:id AND user_id=:uid`,无命中→404(不泄露存在性)。本期以 `refresh_tokens`(用户归属)验证该范式,后续域照搬。

**D7 统一响应与错误格式。** 成功 `{data, meta}`;错误 `{error:{code,message,details}}`,HTTP 状态与 `code` 对齐([`architecture §3.2/§5.2`](../../../docs/tech-solution/architecture.md))。本期落地 `unauthenticated`/`validation_error`/`not_found`/`conflict`/`locked`/`internal_error` 等 code。

**D8 前端 TanStack Query(服务端态)+ Zustand(客户端/token)。** Query 的缓存/失效契合后续任务轮询基线;Zustand 存 token 内存态。REST 客户端封装 401 自动刷新拦截 + 并发刷新去重(共享单次刷新 Promise)([`frontend.md §6/§7`](../../../docs/tech-solution/frontend.md))。

**D9 客户端 token 分层存储。** access → `localStorage`(JS 读后附头);refresh → 内存 / `sessionStorage`(随标签关闭失效)。配合 CSP、输出转义、限制第三方脚本收敛 XSS 面。

## Risks / Trade-offs

- **[access token 存 localStorage 易受 XSS 窃取]** → access 短时(15min)+ 收敛 XSS 面(CSP/转义/限第三方脚本)+ refresh 不入 localStorage;可接受(与 [`user-auth §5`](../../../docs/requirements/features/user-auth.md) 决策一致)。
- **[HS256 共享对称密钥,多实例需共享密钥]** → 密钥经 env(生产 KMS)注入;本期单实例,无瓶颈。→ *缓解*:密钥轮换走 env 重启。
- **[无状态 access 无法即时吊销]** → 短时 15min + refresh 可吊销;登出即吊销 refresh,最多等 access 过期。本期不上 JWT 黑名单。
- **[按账号锁定可被恶意触发锁定他人账号(账号 DoS)]** → 本期无邮箱,无法完全解决;属已接受的权衡(需求侧已裁定,见 [`user-auth §5/§6`](../../../docs/requirements/features/user-auth.md))。
- **[Alembic 初始迁移依赖可用 MySQL]** → 本地/CI 用 docker-compose 起 MySQL 8,迁移在测试前自动 `alembic upgrade head`。
- **[前端独立工程仓库未定]** → 本期可在仓库内(如 `web/` 子目录)先行开发,后续独立仓库;不影响契约。

## Migration Plan

**首次部署(M0):**

1. 起可用的 MySQL 8 实例(utf8mb4);配置 `.env`(`DATABASE_URL`、`JWT_SECRET`、`CORS_ORIGINS` 等)。
2. 后端:`uv sync` → `alembic upgrade head`(建 `users`、`refresh_tokens`)→ `uv run uvicorn drama_smith.main:app`。
3. 前端:`npm install` → `npm run dev`(Vite 代理 `/api` 到后端)或 `npm run build` 出静态产物。
4. 验证:注册→登录→带 token 访问 `GET /api/me`→登出→刷新链路。

**回滚(仅开发期):** `alembic downgrade base` 删除两表;移除后端/前端工程目录。生产走向前迁移 + 兼容期,不做破坏性回滚。

## Open Questions

- 前端**独立工程的仓库位置/命名**(architecture §7 遗留)——本期可先置于仓库内 `web/`,后续再迁。
- JWT 签名算法最终是否升 RS256(非对称,便于多服务验签)?本期 HS256 足够,留待多实例/多服务时再议。
- 登录锁定是否未来引入邮箱解锁?取决于是否开邮箱(本期不开)。
