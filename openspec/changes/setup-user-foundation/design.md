## Context

drama-smith 已决定采用前后端分离的 Web 架构(FastAPI 后端 + React 前端 + MySQL),完整技术方案沉淀于 [`docs/tech-solution/`](../../../docs/tech-solution/)(总纲 / 架构详案 / 数据库设计 / 后端 / 前端),需求侧见 [`docs/requirements/features/user-auth.md`](../../../docs/requirements/features/user-auth.md)(FR-U)。

**仓库布局(已定)**:monorepo —— 前后端同仓,后端在 `backend/`(Python 包 `drama_smith`,src layout),前端在 `frontend/`。**此决策取代了 [`architecture.md §4.4`](../../../docs/tech-solution/architecture.md) 早先的「非 monorepo、前端独立工程」**(见 D10)。

**当前状态**:仓库无后端/前端代码;`openspec/` 此前为空,旧的 `setup-project-foundation`(CLI 单包)已失效。本变更是新架构的第一个落地切片(里程碑 M0),只做「项目地基 + 用户与认证」,为后续里程碑(BYOK 配置、结构化分析、分镜视频流水线等)提供可运行的骨架与 `user_id` 隔离范式。

**约束**:macOS 优先;后端 Python 3.12+、前端 Node 22;敏感配置(JWT 密钥、DB DSN、MEK)经 `.env` 注入、不入库/日志;多租户隔离(NFR-7)、认证与会话安全(NFR-6)为硬约束。

## Goals / Non-Goals

**Goals:**

- 可一条命令安装/运行/测试的后端骨架(`backend/` 下 uv + FastAPI + ruff/mypy/pytest)。
- MySQL 持久化层(SQLAlchemy 2.0 async + Alembic),初始迁移建 `users`、`refresh_tokens`。
- 完整认证流程:注册 / 登录 / 登出 / 刷新 / `GET /api/me`;argon2id + JWT(HS256)+ 可吊销刷新令牌 + 账号维度防爆破。
- 多租户隔离的仓储范式(强制 `user_id` 过滤),后续业务表直接复用。
- 可运行的前端骨架(`frontend/` 下 Vite + React + TS),含登录/注册页、路由守卫、带 401 自动刷新的 REST 客户端、token 分层存储。

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

**D10 monorepo:前后端同仓(`backend/` + `frontend/`)。** 后端 `backend/`(uv + Python 包 `drama_smith`,src layout)、前端 `frontend/`(npm + Vite),各自独立工具链与依赖,同仓便于联调与契约对齐。**取代** [`architecture.md §4.4`](../../../docs/tech-solution/architecture.md) 早先的「非 monorepo、前端独立工程」决策——该决策被本轮调整推翻;相应同步更新 tech-solution 各篇与 `system-architecture.md`。*替代*:分仓(前端独立仓库,更解耦但联调/契约同步成本高)、单包(前后端混在同一目录,工具链互相污染)。同仓 + 各自子目录为本期最优。

**D11 DB 引擎/会话以懒工厂暴露,对齐 `core/config` 的 `get_settings`/`override_settings` 模式。** `db/base.py` 暴露 `get_engine()`(按 `settings.database_url` 建并 memoize 的 `create_async_engine`,`pool_pre_ping=True`、`pool_recycle` 防 MySQL `wait_timeout`)与 `get_session_factory()`(`async_sessionmaker`);`get_session` 依赖与 Alembic `env.py` 复用同一工厂;`lifespan` 调 `get_engine()` 后负责 `await engine.dispose()`。*替代*:模块级 `engine = create_async_engine(...)`(导入即建、测试难改 DB,与阶段六临时库/testcontainers 冲突)、`backend.md §3` 伪码的 `app.state.engine`(生命周期最干净,但 `get_session` 需从 `request.app.state` 取 factory、Alembic 须另起 engine)。懒工厂使阶段六集成测试可经 `override_settings` 重定向到临时库而无需 monkeypatch 模块全局。

**D12 ORM 模型约定(对齐 [`database.md §1`](../../../docs/tech-solution/database.md),逐条落实以免迁移偏移)。** ① **主键 `BIGINT UNSIGNED`** —— `Mapped[int]` + `BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")`、`autoincrement=True`;**外键列类型必须一致**(尤其 `refresh_tokens.user_id`,不一致 MySQL 建表即报错)。② **每表显式 `__table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"}`**(DSN 的 `charset=utf8mb4` 只管连接编码,不管表/列)。③ **时间戳 `DATETIME(3)` 存 naive-UTC**:`created_at`/`updated_at` 用 `mysql.DATETIME(fsp=3)` + `server_default=func.now()`;`updated_at` 配 **MySQL `ON UPDATE CURRENT_TIMESTAMP`**(SQLAlchemy 的 `onupdate=` 仅 ORM 客户端触发,裸 SQL 不更新)。④ **`Base.metadata.naming_convention`** 设约定,保证 autogenerate 产出的约束/索引名稳定、可复现。

**D13 Alembic 迁移接线。** `alembic.ini` 置 `backend/`、`script_location = src/drama_smith/migrations`;`env.py` 先把 `src` 加入 `sys.path` 再 import 包,采用 Alembic **async 模板**(`connectable.run_sync(do_run_migrations)`,因驱动为 asyncmy);`target_metadata = Base.metadata` **之前必须 import 全部模型**(`db/models/__init__.py` 统一 re-export),否则 `--autogenerate` 出空迁移。初始迁移建 `users` + `refresh_tokens` 两表;版本文件入 git。**实现备忘**:
① autogenerate 的 `downgrade` 在 MySQL 上会先 `drop_index` 再 `drop_table`,被外键占用的索引单独 drop 会触发 **MySQL 1553**;生成的迁移须手工删去 `drop_table` 前冗余的 `drop_index`(`drop_table` 级联删索引/外键)—— 后续域凡 `user_id` 索引 + FK 的表同此处理。② 迁移目录须含 `script.py.mako` 模板(`alembic init` 自动生成;本仓库手建目录,需补此文件,否则 revision 阶段报 `FileNotFoundError`)。

**D14 事务边界在 services 层;`get_session` 仅 `yield` 会话 + `close()`,不 commit/rollback。** `get_session`(`async with session_factory() as session: yield session`)只负责会话生命周期;提交/回滚由阶段四/五的 services 用例在用例边界显式控制。依赖层若擅自 commit 会与 services 抢事务边界、引发阶段五返工。

## Risks / Trade-offs

- **[access token 存 localStorage 易受 XSS 窃取]** → access 短时(15min)+ 收敛 XSS 面(CSP/转义/限第三方脚本)+ refresh 不入 localStorage;可接受(与 [`user-auth §5`](../../../docs/requirements/features/user-auth.md) 决策一致)。
- **[HS256 共享对称密钥,多实例需共享密钥]** → 密钥经 env(生产 KMS)注入;本期单实例,无瓶颈。→ *缓解*:密钥轮换走 env 重启。
- **[无状态 access 无法即时吊销]** → 短时 15min + refresh 可吊销;登出即吊销 refresh,最多等 access 过期。本期不上 JWT 黑名单。
- **[按账号锁定可被恶意触发锁定他人账号(账号 DoS)]** → 本期无邮箱,无法完全解决;属已接受的权衡(需求侧已裁定,见 [`user-auth §5/§6`](../../../docs/requirements/features/user-auth.md))。
- **[Alembic 初始迁移依赖可用 MySQL]** → 本地/CI 用 docker-compose 起 MySQL 8,迁移在测试前自动 `alembic upgrade head`。
- **[阶段二验证(2.6)当前指向外部 MySQL]** → `.env` 的 `DS_DATABASE_URL` 指向外部 MySQL(`drama_smith` 库已建空);`alembic upgrade head` / `downgrade base` 在其上可逆、安全。集成测试用的 testcontainers/临时库延后至阶段六,届时经 `override_settings` 重定向(见 D11)。
- **[monorepo 前后端工具链混杂]** → 各自子目录 + 独立锁文件(`backend/uv.lock`、`frontend/package-lock.json`);根目录只放文档与 docker-compose,不引入跨端耦合。

## Migration Plan

**首次部署(M0):**

1. 起可用的 MySQL 8 实例(utf8mb4);配置 `backend/.env`(`DATABASE_URL`、`JWT_SECRET`、`CORS_ORIGINS` 等)。
2. 后端:`cd backend && uv sync` → `alembic upgrade head`(建 `users`、`refresh_tokens`)→ `uv run uvicorn drama_smith.main:app`。
3. 前端:`cd frontend && npm install` → `npm run dev`(Vite 代理 `/api` 到后端)或 `npm run build` 出静态产物。
4. 验证:注册→登录→带 token 访问 `GET /api/me`→登出→刷新链路。

**回滚(仅开发期):** `cd backend && alembic downgrade base` 删除两表;移除 `backend/`、`frontend/` 目录。生产走向前迁移 + 兼容期,不做破坏性回滚。

## Open Questions

- ~~前端**独立工程的仓库位置/命名**(architecture §7 遗留)~~ → **已定(本轮)**:monorepo,前端置于本仓 `frontend/`(见 D10)。
- JWT 签名算法最终是否升 RS256(非对称,便于多服务验签)?本期 HS256 足够,留待多实例/多服务时再议。
- 登录锁定是否未来引入邮箱解锁?取决于是否开邮箱(本期不开)。
