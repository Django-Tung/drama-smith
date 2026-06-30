# Tasks

> 实施依据:[proposal](proposal.md) · [design](design.md) · [specs/user-auth/spec.md](specs/user-auth/spec.md) · 技术方案 [`docs/tech-solution/`](../../../docs/tech-solution/)。
> **仓库为 monorepo**:后端在 `backend/`(Python 包 `drama_smith`,src layout),前端在 `frontend/`。
> 顺序按依赖排列;每组结束有「验证」项作为该组完成判据。

## 1. 后端工程与工具链骨架(`backend/`)

- [x] 1.1 在 `backend/` 下初始化 uv 项目(`backend/pyproject.toml`,Python 3.12+):运行依赖 fastapi、uvicorn[standard]、pydantic、pydantic-settings、sqlalchemy[asyncio]、asyncmy、alembic、argon2-cffi、pyjwt;开发依赖 ruff、mypy、pytest、pytest-asyncio、pytest-cov、httpx
- [x] 1.2 建立分层目录 `backend/src/drama_smith/{api,core,db,migrations}`(含 `__init__.py`)与 `backend/tests/`
- [x] 1.3 配置 `ruff`(format+lint)、`mypy`(strict)、`pytest`;新增 `backend/.env.example`,补 `.gitignore`(`.env`、`__pycache__`、`.venv`、`backend/.venv` 等)
- [x] 1.4 `backend/src/drama_smith/main.py`:FastAPI app、`lifespan`、CORS(源读配置)、`GET /api/health`、`/api` 路由前缀挂载
- [x] 1.5 验证:`cd backend && uv run uvicorn drama_smith.main:app` 起服务,`GET /api/health` 返回 200

## 2. 数据库层(MySQL + SQLAlchemy 2.0 async + Alembic)

- [ ] 2.1 `backend/src/drama_smith/db/base.py`:Declarative Base + async 引擎/会话工厂(`create_async_engine`、`async_sessionmaker`、`pool_pre_ping`),字符集 utf8mb4
- [ ] 2.2 `backend/src/drama_smith/db/session.py`:`get_session` 异步依赖(请求级会话)
- [ ] 2.3 `backend/src/drama_smith/db/models/users.py`:字段对齐 [`database.md §3.1`](../../../docs/tech-solution/database.md)(id、username UNIQUE、password_hash、failed_login_count、locked_until、last_login_at、created_at/updated_at)
- [ ] 2.4 `backend/src/drama_smith/db/models/refresh_tokens.py`:user_id FK+索引、token_hash UNIQUE、expires_at 索引、revoked_at、created_at
- [ ] 2.5 初始化 Alembic(`backend/alembic.ini`、`backend/src/drama_smith/migrations/env.py` 配置 async + metadata),生成初始迁移建 `users` + `refresh_tokens`
- [ ] 2.6 验证:`cd backend && alembic upgrade head` 建表成功;`alembic downgrade base` 可回滚(临时 MySQL)

## 3. 配置与安全原语

- [ ] 3.1 `backend/src/drama_smith/core/config.py`:`Settings`(pydantic-settings)字段 `database_url`、`jwt_secret`(SecretStr)、`jwt_access_ttl`=15min、`refresh_ttl_days`=7、`cors_origins`、`login_max_failures`=5、`login_lock_minutes`=15;敏感字段不入 OpenAPI schema
- [ ] 3.2 `backend/src/drama_smith/core/security.py`:argon2id 密码(`hash_password` / `verify_password`)
- [ ] 3.3 `backend/src/drama_smith/core/security.py`:JWT 签发/校验(`create_access_token` HS256,claims `sub`/`username`/`iat`/`exp`;`verify_access_token`)
- [ ] 3.4 `backend/src/drama_smith/core/security.py`:刷新令牌生成(`secrets.token_urlsafe`)+ 哈希(`hash_refresh_token`)

## 4. 鉴权依赖、多租户范式与错误处理

- [ ] 4.1 `backend/src/drama_smith/core/errors.py`:领域异常 + 全局异常处理器 → 统一错误格式([`architecture §3.2`](../../../docs/tech-solution/architecture.md)),code 含 `unauthenticated`/`validation_error`/`not_found`/`conflict`/`locked`/`internal_error`
- [ ] 4.2 `backend/src/drama_smith/db/repositories/`:`user_repo`、`refresh_token_repo`;方法签名强制带 `user_id`,查询 `WHERE id=:id AND user_id=:uid`,无命中 → 抛 `NotFound`
- [ ] 4.3 `backend/src/drama_smith/api/deps.py`:OAuth2 Bearer scheme + `get_current_user` 依赖(验签 → 取 user → 校验未锁定)

## 5. 认证 API

- [ ] 5.1 `POST /api/auth/register`:校验用户名(3–32,字母数字下划线)+ 密码(≥8 含字母+数字)、唯一性、argon2id 落库、签发 access+refresh(存 refresh 哈希)、201
- [ ] 5.2 `POST /api/auth/login`:校验密码、账号锁定检查、失败递增计数/置 `locked_until`、成功清零并签发 access+refresh、记 `last_login_at`
- [ ] 5.3 `POST /api/auth/refresh`:校验 refresh 哈希 + 未过期 + 未吊销 → 签发新 access
- [ ] 5.4 `POST /api/auth/logout`:将当前 refresh 置 `revoked_at`(吊销)
- [ ] 5.5 `GET /api/me`:返回 id/username + `text_model_configured: false`
- [ ] 5.6 验证:全链路 register → login → /api/me → logout → refresh 行为符合 spec 各场景

## 6. 后端测试与质量门

- [ ] 6.1 集成测试:register/login/logout/refresh/me 正常与异常路径(临时 MySQL,先 `alembic upgrade head`)
- [ ] 6.2 测试:防爆破(5 次锁定、15min 自动解锁、成功重置计数)
- [ ] 6.3 测试:无 token/坏 token → 401;越权访问他人资源 → 404;列表按 `user_id` 过滤
- [ ] 6.4 质量门:`cd backend && ruff check . && mypy . && pytest --cov` 达约定阈值全绿

## 7. 前端工程骨架(`frontend/`)

- [ ] 7.1 在 `frontend/` 下初始化 Vite + React + TS(Node 22);`frontend/package.json`、`tsconfig`(strict)、`vite.config.ts`(代理 `/api`、`/ws` 到后端)
- [ ] 7.2 配置 ESLint + Prettier;建目录 `frontend/src/{routes,components,features,api,realtime,stores,hooks,types,utils}`
- [ ] 7.3 `frontend/src/types/`:与后端契约对齐的 TS 类型(`User`、`AuthTokens`、`ApiError` 等)
- [ ] 7.4 `frontend/src/api/client.ts`:fetch 封装(基址、`Authorization` 头、解包 `{data,meta}`、抛 `ApiError`)
- [ ] 7.5 `frontend/src/api/endpoints.ts`:auth `register`/`login`/`logout`/`refresh`、`getMe`

## 8. 前端认证实现

- [ ] 8.1 `frontend/src/stores/auth.ts`(Zustand):access→`localStorage`、refresh→内存/`sessionStorage` 分层存储;`login`/`logout` actions
- [ ] 8.2 `frontend/src/api/client.ts`:401 自动刷新拦截(调 `/refresh`)+ 并发刷新去重(共享单次 Promise)+ 重试原请求
- [ ] 8.3 `frontend/src/routes`:登录页、注册页(React Hook Form + Zod,校验规则对齐后端)
- [ ] 8.4 React Router 路由 + `RequireAuth` 守卫(无 token 且刷新失败 → 重定向 `/login`)
- [ ] 8.5 验证:`cd frontend && npm run dev` 跑通注册 → 登录 → 受保护页 → 登出;access 过期触发自动刷新

## 9. 联调与收尾

- [ ] 9.1 前后端本地联调(根 `docker-compose` MySQL + `cd backend && uv run uvicorn ...` + `cd frontend && npm run dev`)
- [ ] 9.2 补 `backend/.env.example`、起服务说明(根 README 汇总 backend/frontend 启动)
- [ ] 9.3 `openspec status --change setup-user-foundation` 确认工件齐备、可 `/opsx:apply`
