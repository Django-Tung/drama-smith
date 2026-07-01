# drama-smith 后端(`backend/`)

FastAPI 后端,monorepo 的后端目录(src layout 包 `drama_smith`)。

> 技术方案见 [`../docs/tech-solution/backend.md`](../docs/tech-solution/backend.md)。
> 当前进度:里程碑 **M0(项目地基 + 用户认证)** 已落地,见 [`../openspec/changes/setup-user-foundation/tasks.md`](../openspec/changes/setup-user-foundation/tasks.md)。总览启动说明见 [`../README.md`](../README.md)。

## 环境要求

- Python 3.12+(由 `uv` 自动管理)
- [uv](https://docs.astral.sh/uv/) 0.11+
- 可访问的外部 MySQL 8 实例(连接串写入 `.env`,见下)

## 配置

复制 `.env.example` 为 `.env` 并填入真实值(字段以 `DS_` 为前缀):

- `DS_DATABASE_URL` —— 外部 MySQL 连接串(`mysql+asyncmy://USER:PASSWORD@HOST:3306/drama_smith?charset=utf8mb4`)
- `DS_JWT_SECRET` —— JWT 签名密钥(生产务必随机,如 `openssl rand -base64 48`)
- 其余(CORS、令牌有效期、登录防爆破阈值)均有合理默认,按需调整

> MySQL 为**外部实例**(非本地 docker),连接信息仅存 `.env`(已 gitignore)。
> 集成测试库 `drama_smith_test` 由夹具自动创建(派生自 `DS_DATABASE_URL` 的 `<库名>_test`,或显式 `DS_TEST_DATABASE_URL`)。

## 常用命令

```bash
cd backend

uv sync                                       # 安装依赖(创建 .venv 并锁定 uv.lock)
uv run alembic upgrade head                   # 建表/迁移(初始迁移建 users + refresh_tokens)
uv run uvicorn drama_smith.main:app --reload  # 起开发服务(默认 :8000)

uv run ruff check .                           # 质量门:lint
uv run ruff format --check .                  # 格式检查
uv run mypy .                                 # strict 类型检查
uv run pytest                                 # 集成测试(含覆盖率,阈值 90%)
```

- Swagger UI:`http://localhost:8000/docs`(OpenAPI:`/openapi.json`)
- API:`POST /api/auth/{register,login,refresh,logout}`、`GET /api/me`、`GET /api/health`

## 目录

```
backend/
├── pyproject.toml          # uv 项目 + 工具链(ruff / mypy / pytest / coverage)
├── alembic.ini             # Alembic 配置
├── .env.example            # 配置示例(DS_ 前缀)
├── src/drama_smith/
│   ├── main.py             # FastAPI app + lifespan + CORS + 路由挂载 + 异常处理
│   ├── api/                # 接口层:auth / me / health / deps / schemas
│   ├── core/               # config / security(argon2 + JWT + refresh) / errors
│   ├── db/                 # SQLAlchemy 模型 + 会话 + 仓储(user / refresh_token)
│   └── migrations/         # Alembic
└── tests/                  # 集成测试:auth_flow / brute_force / access_control
```
