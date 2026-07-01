# Tasks

> 实施依据:[proposal](proposal.md) · [design](design.md) · [specs/ai-config/spec.md](specs/ai-config/spec.md) · [specs/user-auth/spec.md](specs/user-auth/spec.md) · 技术方案 [`docs/tech-solution/`](../../../docs/tech-solution/)。
> **仓库为 monorepo**:后端在 `backend/`(Python 包 `drama_smith`,src layout),前端在 `frontend/`;承接 M0(`setup-user-foundation`)地基,复用其 ORM/事务/错误范式(见该变更 D12/D14、[`backend.md §10`](../../../docs/tech-solution/backend.md))。
> 顺序按依赖排列;每组末尾「验证」项为该组完成判据。

## 1. 依赖、配置与 MEK 注入

- [ ] 1.1 `backend/pyproject.toml` 新增运行依赖 `cryptography`(AES-GCM)、`litellm`(文本/图片接缝);`uv sync` 更新锁文件
- [ ] 1.2 `backend/src/drama_smith/core/config.py`:`Settings` 增 `ds_mek: SecretStr`;`model_config` 标注其不入 OpenAPI schema;新增 `get_mek() -> bytes`(`base64.b64decode`,32B 校验)
- [ ] 1.3 启动期 fail-fast:`get_mek()` 校验存在且为 32B,否则抛明确错误拒绝启动(避免静默落弱密钥)
- [ ] 1.4 更新 `backend/.env.example`:补 `DS_MEK` 及「`openssl rand -base64 32` 生成并备份」说明;补 README 启动段
- [ ] 1.5 验证:`cd backend && uv run python -c "from drama_smith.core.config import get_mek; print(len(get_mek()))"` 在配好 `DS_MEK` 时输出 32;缺失/非 32B 时启动报错

## 2. 信封加密原语(`core/crypto.py`)

- [ ] 2.1 `backend/src/drama_smith/core/crypto.py`:`encrypt(plaintext: str, mek: bytes) -> Envelope`(DEK=`urandom(32)`、AES-256-GCM 加密明文得 `ciphertext`+12B `iv`、MEK 封 DEK 得 `dek_ciphertext`)、`decrypt(env: Envelope, mek: bytes) -> str`,对齐 [`backend.md §9`](../../../docs/tech-solution/backend.md)
- [ ] 2.2 脱敏函数 `mask_key(key: str) -> str`(`key[:3]+"…"+key[-4:]`,对齐 [`database.md §6`](../../../docs/tech-solution/database.md))
- [ ] 2.3 单元测试:加解密往返一致、不同明文产生不同 DEK/密文、`decrypt` 用错 MEK 失败、`mask_key` 边界(短 key)
- [ ] 2.4 验证:`cd backend && uv run pytest tests/unit/test_crypto.py` 全绿;断言明文不出现在任何中间产物

## 3. `model_configs` 表与迁移

- [ ] 3.1 `backend/src/drama_smith/db/models/model_configs.py`:字段对齐 [`database.md §3.2`](../../../docs/tech-solution/database.md) —— `id`(BIGINT UNSIGNED)、`user_id`(FK→users + 索引)、`purpose`(ENUM text/image/video)、`provider`、`model`、`base_url`、`api_key_ciphertext`/`api_key_iv`/`dek_ciphertext`(VARBINARY)、`params`/`provider_options`(JSON)、`is_active`(默认 0)、`status`(ENUM active/invalid,默认 active)、`last_tested_at`、`created_at`/`updated_at`;遵守 M0 ORM 约定(utf8mb4、`DATETIME(3)` naive-UTC、naming_convention)
- [ ] 3.2 生成列 `active_key`:`GENERATED ALWAYS AS (CASE WHEN is_active=1 THEN CONCAT(user_id,'-',purpose) END) VIRTUAL` + `UNIQUE` 索引(MySQL 允许多行 NULL,保证每 `(user_id,purpose)` 恰一条 active,见 design D3)
- [ ] 3.3 `db/models/__init__.py` re-export `ModelConfig`(Alembic autogenerate 必需,承接 M0 D13)
- [ ] 3.4 Alembic 迁移建表;手写/校准生成列 + UNIQUE 索引;按 M0 经验处理 drop 顺序(避免 MySQL 1553)
- [ ] 3.5 验证:`cd backend && alembic upgrade head` 建 `model_configs` 成功;`alembic downgrade -1` 可回滚

## 4. 仓储层(`db/repositories/model_config_repo.py`)

- [ ] 4.1 方法签名一律带 `user_id`(承接 M0 D6):`list(user_id, purpose?)`、`get(user_id, id)`(无命中→`NotFound`)、`create`、`update`、`delete`、`count_active(user_id, purpose)`、`has_active_text(user_id)`(`EXISTS` 查询)
- [ ] 4.2 `activate(user_id, id)`:单事务内先把同 `(user_id,purpose)` 的 active 置 0,再置目标行 1(对齐 design D3)
- [ ] 4.3 `set_status(user_id, id, status)`:`UPDATE ... WHERE id AND user_id`(FR-C5 invalid 标记)
- [ ] 4.4 单元测试(临时/外部 MySQL,先 `alembic upgrade head`):首条自动 active、`activate` 翻转保证唯一 active、跨用户 `get` 返回 `NotFound`、`has_active_text` 真值
- [ ] 4.5 验证:`cd backend && uv run pytest tests/unit/test_model_config_repo.py` 全绿;构造两用户数据断言跨用户隔离

## 5. `core/llm` 供应商无关接缝(`llm/`)

- [ ] 5.1 `backend/src/drama_smith/llm/base.py`:`TextModel`/`ImageModel`/`VideoModel` Protocol(`chat`/`generate`/`submit`+`poll`),对齐 [`backend.md §6`](../../../docs/tech-solution/backend.md)
- [ ] 5.2 `llm/factory.py`:`build(model_config_snapshot, plaintext_key, mek) -> Model`;按 purpose 构造(text/image→litellm、video→`adapters/<provider>`)
- [ ] 5.3 `llm/litellm_text.py`/`litellm_image.py`:litellm 适配;`llm/adapters/__init__.py` 抽象 `VideoAdapter` 协议(本期落占位,M3 首批接入,见 design D5)
- [ ] 5.4 零成本探测能力:`TextModel`/`ImageModel` 提供 `probe()`(列模型/最小鉴权探测,不真生成,对齐 design D6)
- [ ] 5.5 供应商白名单:`llm/base.py` 按 purpose 的常量表,取自 [`ai-config §2.1`](../../../docs/requirements/features/ai-config.md);`validate_provider(purpose, provider)` 供 API 层调用
- [ ] 5.6 测试替身:`tests/llm/fakes.py` 的 `FakeTextModel`/`FakeImageModel`(确定性输出、可控 `probe` 成败),承接 [`backend.md §11`](../../../docs/tech-solution/backend.md)
- [ ] 5.7 验证:`core/llm` 不 import 任何 `graphs`/`services`(分层自检,`grep -R "import litellm" src/drama_smith/{graphs,services,analysis}` 无命中)

## 6. service 层(`services/model_config_service.py`)

- [ ] 6.1 用例:创建(白名单校验→加密落库→首条自动 active)、更新(`api_key` 缺省不动加密列,design D8)、删除(删 active 时的处理,design D4)、activate、self-test
- [ ] 6.2 删除 active 规则:同 purpose 仍有其他配置→要求显式 `new_active_id`(否则 409 `invalid_state`);删除后 0 条→text 类回到未配态、image/video 仅禁用(对齐 design D4、spec)
- [ ] 6.3 自检 `test_config(user_id, id)`:解密 Key→`factory.build`→`probe()`→回写 `last_tested_at`;遇 401/403/鉴权失败→`set_status(invalid)` + 抛 `ProviderAuthFailed`(design D7)
- [ ] 6.4 超时/重试/限流:自检/探测路径按 purpose 默认超时与有限重试;429/超时→`RateLimited`(`rate_limited`),不无限阻塞(design D6/D7)
- [ ] 6.5 预留 `require_active_text(user_id)`:无 active 文本配置→抛 `ModelNotConfigured`(为 M2 分析门禁预留,本期不被调用)
- [ ] 6.6 事务边界在 service(承接 M0 D14):`get_session` 仅 yield,提交/回滚在用例边界
- [ ] 6.7 验证:`cd backend && uv run pytest tests/unit/test_model_config_service.py`(Fake LLM 替身)覆盖各用例与 FR-C5/C6 映射

## 7. 错误码、依赖接线与路由挂载

- [ ] 7.1 `core/errors.py` 增 `ModelNotConfigured`(409 `model_not_configured`)、`ProviderAuthFailed`(502 `provider_auth_failed`)、`RateLimited`(502 `rate_limited`)、`QuotaExceeded`(429 `quota_exceeded`),并在全局异常处理器登记,对齐 [`backend.md §10`](../../../docs/tech-solution/backend.md)
- [ ] 7.2 `api/deps.py`:`get_crypto()` 依赖(读 `get_mek()`,支持测试 `override_settings`)
- [ ] 7.3 `main.py`:挂载 models 路由;CORS/lifespan 不变
- [ ] 7.4 验证:`cd backend && uv run uvicorn drama_smith.main:app` 起服务;`/openapi.json` 含 `model_not_configured`/`provider_auth_failed`/`rate_limited`/`quota_exceeded` 且 `ds_mek` 不在 schema

## 8. 模型配置 API(`api/models.py`)

- [ ] 8.1 `api/schemas.py`:`ModelConfigCreate`/`Update`(provider 白名单校验、`api_key` 可选)、`ModelConfigPublic`(**仅脱敏 key**,明文永不出现)
- [ ] 8.2 `GET /api/me/models`(列表,按 purpose 可选过滤)、`GET /api/me/models/:id`(详情,均脱敏 key)
- [ ] 8.3 `POST /api/me/models`(创建,201)、`PUT /api/me/models/:id`(更新,缺省 key 不动加密列)、`DELETE /api/me/models/:id`(删 active 规则见 6.2)
- [ ] 8.4 `POST /api/me/models/:id/activate`(事务内翻转 active)
- [ ] 8.5 `POST /api/me/models/:id/test`(零成本自检,不真生成)
- [ ] 8.6 修改 `GET /api/me`:`text_model_configured` 取 `has_active_text(user_id)` 真实值(对齐 [`architecture §3.3`](../../../docs/tech-solution/architecture.md)、design D9)
- [ ] 8.7 验证:`cd backend && uv run pytest tests/integration/test_models_api.py` 覆盖 CRUD/activate/test 正常与异常、跨用户 404、`/api/me` 标记随配置翻转

## 9. 后端测试与质量门

- [ ] 9.1 集成测试:模型配置 CRUD/activate/test 正常路径 + 错误路径(422 白名单、409 active 规则、502 鉴权失败→invalid)
- [ ] 9.2 安全测试:断言**任何响应/日志不含明文 key**;脱敏格式正确;跨用户访问 404
- [ ] 9.3 `/api/me` 标记生命周期:配/删文本配置后 `text_model_configured` 翻转;image/video 不影响该标记
- [ ] 9.4 质量门:`cd backend && ruff check . && mypy . && pytest --cov` 达约定阈值全绿(`core/crypto`、`llm/factory`、`model_config_service` 为重点覆盖)

## 10. 前端类型与 API 客户端

- [ ] 10.1 `frontend/src/types/`:与后端契约对齐的 TS 类型(`ModelConfig`/`ModelConfigCreate`/`ModelConfigUpdate`/`ModelPurpose`/`Provider` 等;key 字段为脱敏串)
- [ ] 10.2 `frontend/src/api/endpoints.ts`:models 段 —— `list/create/update/delete/activate/test`、复用 M0 的 fetch 封装(401 自动刷新拦截)

## 11. 前端配置向导 + 设置页

- [ ] 11.1 `frontend/src/features/ai-config/Wizard`:文本必配(自检通过方可继续)、图片/视频步骤可跳过;表单用 React Hook Form + Zod(校验对齐后端)
- [ ] 11.2 登录/刷新后读 `/api/me`:`text_model_configured===false` → 重定向 `/setup` 向导(对齐 design D11)
- [ ] 11.3 `frontend/src/routes/settings`:模型配置增删改、每类用途切换当前生效、单条自检;TanStack Query 驱动(列表 + mutation 失效缓存)
- [ ] 11.4 删除 active 的交互:同 purpose 有其他配置时要求选新 active(对齐 6.2)
- [ ] 11.5 验证:`cd frontend && npm run dev` 跑通:新用户登录 → 向导 → 配文本(自检通过)→ 进主功能 → 设置页增删改/切换/自检;`text_model_configured` 状态一致

## 12. 联调与收尾

- [ ] 12.1 前后端本地联调(根 `docker-compose` MySQL + `cd backend && uv run uvicorn ...` + `cd frontend && npm run dev`);生成并备份 `DS_MEK`
- [ ] 12.2 更新 `backend/.env.example`(1.4 已起步)与根 README 启动说明(`DS_MEK` 生成、新增依赖 `cryptography`/`litellm`)
- [ ] 12.3 `openspec status --change setup-byok-config` 确认工件齐备、可 `/opsx:apply`
