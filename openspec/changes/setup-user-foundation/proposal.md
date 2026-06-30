## Why

drama-smith 已转向前后端分离的 Web 架构(FastAPI 后端 + 独立 React 前端 + MySQL)。在叠加 BYOK 模型配置、结构化分析等后续里程碑之前,必须先落地**多用户地基**:让用户能注册、登录、维持会话,并为所有后续业务数据确立「按用户归属隔离」的范式。旧的 `setup-project-foundation`(CLI 单包架构)已失效,本变更新建 web 架构、作为其取代者,是整个新架构的第一个变更。

## What Changes

- **新建后端工程骨架**(Python 3.12+ / uv / FastAPI):分层目录(`api/core/db/migrations`)、配置(`pydantic-settings` 读 `.env`)、CORS、lifespan、统一错误响应格式、`ruff`+`mypy`+`pytest` 工具链。
- **新建 MySQL 持久化层**:SQLAlchemy 2.0 async(`asyncmy`)+ Alembic;初始迁移建 `users`、`refresh_tokens` 两表(字段对齐 [`docs/tech-solution/database.md §3.1`](../../../docs/tech-solution/database.md))。
- **新增用户与认证能力**:注册 / 登录 / 登出 / 令牌刷新、`GET /api/me`(含「是否已配置文本模型」完成度占位)。
- **密码** argon2id;**访问令牌** JWT(HS256,15min,无服务端状态);**刷新令牌**不透明随机串、仅存哈希、可吊销、7 天。
- **登录防爆破**:仅按账号维度(连续 5 次失败锁 15min,自动解锁;不按 IP)。
- **多租户隔离地基**:仓储层强制 `user_id` 过滤的范式(本期落地 users 相关,后续域复用;越权访问 → 404)。
- **新建前端工程骨架**(Node 22 + React + TS + Vite):React Router 路由 + 守卫、登录/注册页、REST 客户端封装(统一错误、401 自动刷新拦截、并发刷新去重)、token 分层存储、ESLint + Prettier。

## Capabilities

### New Capabilities

- `user-auth`: 用户注册、登录、登出、访问/刷新令牌签发与校验、当前用户信息;密码 argon2id 哈希、JWT(HS256)短时访问令牌 + 可吊销刷新令牌、登录失败按账号锁定;以及「用户数据按 `user_id` 归属隔离」的仓储范式(本期为地基,后续业务表复用)。

### Modified Capabilities

<!-- openspec/specs/ 当前为空,无既有能力;本变更新建首个能力,无修改项。 -->

## Impact

- **代码**:新建后端 `src/drama_smith/`(`api/core/db/migrations/`)与前端独立工程(命名待定);首次引入 FastAPI、SQLAlchemy 2.0、Alembic、asyncmy、argon2-cffi、PyJWT、React、Vite、TanStack Query、Zustand 等依赖。
- **API**:新增 `POST /api/auth/{register,login,logout,refresh}`、`GET /api/me`(契约见 [`docs/tech-solution/architecture.md §3.3`](../../../docs/tech-solution/architecture.md))。
- **数据库**:新增 `users`、`refresh_tokens` 两表;后续里程碑所有业务表将以 `user_id` 外键关联,复用本期确立的隔离范式。
- **系统/依赖**:需可用的 MySQL 8 实例与 Node 22 运行时;敏感配置(JWT 密钥、DB DSN)经 `.env` 注入、不入库/日志。
- **文档**:实施依据已沉淀于 [`docs/tech-solution/`](../../../docs/tech-solution/) 与 [`docs/requirements/features/user-auth.md`](../../../docs/requirements/features/user-auth.md),本变更为其首个落地切片(M0)。
