# drama-smith 后端(`backend/`)

FastAPI + LangGraph 后端,monorepo 的后端目录(src layout 包 `drama_smith`)。

> 技术方案见 [`../docs/tech-solution/backend.md`](../docs/tech-solution/backend.md)。
> 本期(M0)仅落地「地基 + 用户认证」,实施进度见 [`../openspec/changes/setup-user-foundation/tasks.md`](../openspec/changes/setup-user-foundation/tasks.md)。

## 环境要求

- Python 3.12+(由 `uv` 自动管理)
- [uv](https://docs.astral.sh/uv/) 0.11+

## 常用命令

```bash
cd backend

# 安装依赖(创建 .venv 并锁定 uv.lock)
uv sync

# 起开发服务
uv run uvicorn drama_smith.main:app --reload

# 质量门
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest

# 数据库迁移(后续任务组启用)
# uv run alembic upgrade head
```

## 配置

复制 `.env.example` 为 `.env` 并按需修改(字段以 `DS_` 为前缀)。当前骨架仅需 `DS_ENVIRONMENT`、`DS_CORS_ORIGINS`;MySQL/JWT 等字段在后续任务组启用。

## 目录

```
backend/
├── pyproject.toml          # uv 项目 + 工具链配置(ruff/mypy/pytest)
├── .env.example
├── src/drama_smith/
│   ├── main.py             # FastAPI app + lifespan + CORS + /api 挂载
│   ├── api/                # 接口层(health;后续 auth/me/…)
│   ├── core/               # config / security / crypto / errors / logging(按任务组补)
│   ├── db/                 # SQLAlchemy 模型 + 会话 + 仓储(任务组 2/4)
│   └── migrations/         # Alembic(任务组 2)
└── tests/
```
