# drama-smith

结构化剧本分析 + 分镜视频生产流水线。前后端分离的 monorepo:**FastAPI** 后端(`backend/`)+ **React + Vite** 前端(`frontend/`)+ **MySQL 8** 持久化。

> 当前进度:里程碑 **M0(项目地基 + 用户认证)** 已落地,见 [`openspec/changes/setup-user-foundation/`](openspec/changes/setup-user-foundation/)。
> 完整技术方案见 [`docs/tech-solution/`](docs/tech-solution/),需求见 [`docs/requirements/`](docs/requirements/)。

## 仓库结构

```
drama-smith/
├── backend/     # Python 3.12 + uv,FastAPI 包 drama_smith(src layout)
├── frontend/    # Node 20+ + Vite,React + TS(用 yarn)
├── docs/        # 技术方案与需求文档
└── openspec/    # spec-driven 变更工件(proposal / design / specs / tasks)
```

## 前置条件

- **Python 3.12+** 与 [uv](https://docs.astral.sh/uv/) 0.11+
- **Node 20+**(开发建议 22)与 [yarn](https://yarnpkg.com/) 1.22(前端用 yarn,见 `frontend/yarn.lock`)
- **MySQL 8** 实例(外部;连接信息经 `.env` 注入,见下)

## 数据库(外部 MySQL,经 `.env` 配置)

本项目**不依赖本地 docker MySQL**;MySQL 为外部实例,连接串写入 `backend/.env`。

1. 在该 MySQL 上创建空库(utf8mb4):
   ```sql
   CREATE DATABASE drama_smith CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
   ```
2. 表结构由 Alembic 迁移创建(见后端启动步骤)。
3. 集成测试库 `drama_smith_test` 由测试夹具自动创建(派生自 `DS_DATABASE_URL` 的 `<库名>_test`,或显式 `DS_TEST_DATABASE_URL`)。

## 快速开始

### 后端(`backend/`)

```bash
cd backend

# 1. 配置:复制示例并填入外部 MySQL 连接串与 JWT 密钥
cp .env.example .env
#    DS_DATABASE_URL=mysql+asyncmy://USER:PASSWORD@HOST:3306/drama_smith?charset=utf8mb4
#    DS_JWT_SECRET=$(openssl rand -base64 48)   # 生产务必替换为安全随机值
#    DS_MEK=$(openssl rand -base64 32)          # BYOK 信封加密主密钥(base64 32B),务必离线备份!

# 2. 安装依赖(含 cryptography、litellm —— BYOK 信封加密 / 供应商无关调用)
uv sync

# 3. 建表(迁移建 users / refresh_tokens / model_configs)
uv run alembic upgrade head

# 4. 起开发服务(默认 :8000)
uv run uvicorn drama_smith.main:app --reload
```

- 健康检查:`GET http://localhost:8000/api/health`
- Swagger UI:`http://localhost:8000/docs`(OpenAPI:`/openapi.json`)
- 认证 API:`POST /api/auth/{register,login,refresh,logout}`、`GET /api/me`
- BYOK 模型配置:`/api/me/models`(CRUD / activate / 零成本自检);登录后前端据 `text_model_configured` 路由到 `/setup` 向导

质量门:

```bash
cd backend
uv run ruff check .        # lint
uv run mypy .              # strict 类型检查
uv run pytest              # 集成测试(含覆盖率,阈值 90%)
```

### 前端(`frontend/`)

```bash
cd frontend

yarn install
yarn dev                   # 默认 :5173,Vite 代理 /api 与 /ws 到后端 :8000
```

开发态浏览器打开 `http://localhost:5173`。Vite 把 `/api/*`、`/ws/*` 代理到后端(`:8000`,见 `vite.config.ts`),故开发期无需在前端配置 API 基址;生产构建由 `VITE_API_BASE` 决定。

## 配置项

后端配置以 `DS_` 为前缀,从 `backend/.env` 读取(示例见 `backend/.env.example`):

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `DS_ENVIRONMENT` | 运行环境(`dev` / `test` / `prod`) | `dev` |
| `DS_DATABASE_URL` | 外部 MySQL 连接串(asyncmy) | 本地兜底值 |
| `DS_JWT_SECRET` | JWT 签名密钥(生产强制覆盖) | 开发兜底值 |
| `DS_JWT_ACCESS_TTL_SECONDS` | 访问令牌有效期 | `900`(15min) |
| `DS_REFRESH_TTL_DAYS` | 刷新令牌有效期 | `7` |
| `DS_MEK` | BYOK 信封加密主密钥(base64 32B;`openssl rand -base64 32`,务必离线备份) | —(必填) |
| `DS_LOGIN_MAX_FAILURES` | 登录连续失败上限 | `5` |
| `DS_LOGIN_LOCK_MINUTES` | 账号锁定时长 | `15` |
| `DS_CORS_ORIGINS` | 允许来源(逗号分隔) | `http://localhost:5173` |
| `DS_TEST_DATABASE_URL` | 测试库(可选;不设则派生 `<db>_test`) | — |

> 敏感字段仅放本地 `.env`(已 gitignore),切勿提交。

## 更多

- 技术方案:[`docs/tech-solution/`](docs/tech-solution/)(架构 / 数据库 / 后端 / 前端)
- 变更管理:[`openspec/`](openspec/) —— `openspec list` 查看变更,`/opsx:apply <change>` 实施
