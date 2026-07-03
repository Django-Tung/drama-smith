# Tasks

> 实施依据:[proposal](proposal.md) · [design](design.md) · [specs/ai-config/spec.md](specs/ai-config/spec.md) · [specs/user-auth/spec.md](specs/user-auth/spec.md) · 技术方案 [`docs/tech-solution/`](../../../docs/tech-solution/)。
> **仓库为 monorepo**:后端在 `backend/`(Python 包 `drama_smith`,src layout),前端在 `frontend/`;承接 M0(`setup-user-foundation`)地基,复用其 ORM/事务/错误范式(见该变更 D12/D14、[`backend.md §10`](../../../docs/tech-solution/backend.md))。
> 顺序按依赖排列;每组末尾「验证」项为该组完成判据。

## 1. 依赖、配置与 MEK 注入

- [x] 1.1 `backend/pyproject.toml` 新增 `litellm`(`cryptography` M0 期已随 asyncmy 在位);`uv sync` 装妥(litellm 1.90.2)
- [x] 1.2 `core/config.py`:`Settings` 增 `mek: SecretStr`(env_prefix `ds_` → `DS_MEK`,与 jwt_secret 同范式;原写的字段名 `ds_mek` 会双前缀,已更正);新增 `get_mek() -> bytes`(`base64.b64decode` + 32B 校验)
- [x] 1.3 启动期 fail-fast:`mek` 必填(缺失 → `Settings()` 即拒)、`get_mek()` 校验 32B(非 base64/非 32B → `ValueError`);均经验证
- [x] 1.4 `.env.example` 补 `DS_MEK` + 生成/备份说明;本地 `.env` 已注入实参 MEK(README 启动段并入 12.2)
- [x] 1.5 验证:`get_mek()` 返回 32B;非 32B / 非 base64 均抛 `ValueError`(已跑通)

## 2. 信封加密原语(`core/crypto.py`)

- [x] 2.1 `core/crypto.py`:`encrypt/decrypt` + `_seal/_open`,两层对称自包含 blob(`nonce‖ct‖tag`),**裁定 A2**(design D1):删 `api_key_iv`、两列 `api_key_ciphertext`/`dek_ciphertext`;原 `backend.md §9` 伪码会丢 DEK nonce,源文档待收尾同步
- [x] 2.2 `mask_key`(`key[:3]+"…"+key[-4:]`,< 8 位回退 `…` 防泄露全串)
- [x] 2.3 单元测试 `tests/unit/test_crypto.py`:往返、每次新 DEK/nonce、错 MEK/篡改 `InvalidTag`、明文不入密文、`mask_key` 边界
- [x] 2.4 验证:`pytest tests/unit/test_crypto.py` 10 绿

## 3. `model_configs` 表与迁移

- [x] 3.1 `db/models/model_configs.py`:字段按 **A2+m2** 调整——删 `api_key_iv`、加 `api_key_masked VARCHAR(32)`(两 blob 列 `api_key_ciphertext`/`dek_ciphertext`);余列对齐 `database.md §3.2`、遵守 M0 ORM 约定(utf8mb4、`DATETIME(3)`、naming_convention)
- [x] 3.2 `active_key` VIRTUAL 生成列 + `UNIQUE`(已在 MySQL 8.0.46 实测建表成功)
- [x] 3.3 `db/models/__init__.py` re-export `ModelConfig`
- [x] 3.4 迁移 `04569358397f_add_model_configs`(autogenerate 产出干净 DDL:VIRTUAL 生成列 + UNIQUE 正确);downgrade 按 M0 经验只 `drop_table`(避免 1553)
- [x] 3.5 验证:`upgrade head` 建表成功;`downgrade -1` → `upgrade head` 往返通过

## 4. 仓储层(`db/repositories/model_config_repo.py`)

- [x] 4.1 方法签名一律带 `user_id`(承接 M0 D6):`list(user_id, purpose?)`、`get(user_id, id)`(无命中→`NotFound`)、`create`、`update`(`_UNSET` 哨兵,D8 key 保留)、`delete`、`count_active(user_id, purpose)`、`has_active_text(user_id)`(`EXISTS` 查询)
- [x] 4.2 `activate(user_id, id)`:单事务内先把同 `(user_id,purpose)` 的 active 置 0,再置目标行 1(对齐 design D3);UNIQUE 兜底竞态
- [x] 4.3 `set_status(user_id, id, status)`:`UPDATE ... WHERE id AND user_id`(FR-C5 invalid 标记)
- [x] 4.4 单元测试(复用 `tests/conftest.py` session 夹具自动 `CREATE DATABASE` + `alembic upgrade head`):首条自动 active、`activate` 翻转保证唯一 active、跨用户 `get` 返回 `NotFound`、`has_active_text` 真值
- [x] 4.5 验证:`cd backend && uv run pytest tests/unit/test_model_config_repo.py` 9 绿;两用户数据断言跨用户隔离

## 5. `core/llm` 供应商无关接缝(`llm/`)

- [x] 5.1 `backend/src/drama_smith/llm/base.py`:`TextModel`/`ImageModel`/`VideoModel` Protocol(`chat`/`generate`/`submit`+`poll`),对齐 [`backend.md §6`](../../../docs/tech-solution/backend.md)
- [x] 5.2 `llm/factory.py`:`build(snapshot, plaintext_key) -> TextModel|ImageModel|VideoModel`;按 purpose 构造(text/image→litellm、video→`adapters/<provider>`)。**原写 `build(..., mek)`,已改为 service 解密后只传 `plaintext_key`,保持 `llm/` 不 import crypto(任务 5.7)**
- [x] 5.3 `llm/litellm_text.py`/`litellm_image.py`:litellm 适配;`llm/adapters/__init__.py` 抽象 `VideoModel` 协议 + `build_video_adapter` 占位(本期落占位,M3 首批接入,见 design D5)
- [x] 5.4 零成本探测能力:`TextModel`/`ImageModel` 提供 `probe()`,经 OpenAI 兼容 `GET /models` 打(litellm 无统一零成本探测路径);状态映射 401/403→`ProviderAuthFailed`、429/5xx/超时→`RateLimited`、404→`ProbeNotSupported`(对齐 design D6)
- [x] 5.5 供应商白名单:`llm/base.py` 按 purpose 的常量表(`TEXT/IMAGE/VIDEO_PROVIDERS`),取自 [`ai-config §2.1`](../../../docs/requirements/features/ai-config.md);`validate_provider(purpose, provider)` 供 API 层调用
- [x] 5.6 测试替身:`tests/llm/fakes.py` 的 `FakeTextModel`/`FakeImageModel`(确定性输出、可控 `probe` 成败),承接 [`backend.md §11`](../../../docs/tech-solution/backend.md);另 `tests/llm/test_llm.py` 覆盖白名单/factory/探测状态映射(20 用例)
- [x] 5.7 验证:`core/llm` 不 import 任何 `graphs`/`services`/`crypto`(分层自检,`grep -R "import litellm" src/drama_smith/{graphs,services,analysis}` 无命中;且 litellm 仅出现于 `llm/litellm_text.py`/`litellm_image.py`)

## 6. service 层(`services/model_config_service.py`)

- [x] 6.1 用例:创建(白名单校验→加密落库→首条自动 active)、更新(`api_key` 缺省不动加密列,design D8)、删除(删 active 时的处理,design D4)、activate、self-test —— 落 `services/model_config_service.py`,另加 `list_configs`/`get_config` 薄封装(API 层只经 service)
- [x] 6.2 删除 active 规则:同 purpose 仍有兄弟→须显式 `new_active_id`(缺则 409 `invalid_state`,details.reason 标记);0 条则直接删(text 经 `has_active_text` 自然回未配态,image/video 仅禁用 —— 此区分是 UX 而非 service 分支)。继任须同 `(user,purpose)` 否则 `NotFound`;先 activate 继任(旧 active 经 bulk update 翻 0)再删,全程至多一条 active
- [x] 6.3 自检 `test_config(user_id, id, *, mek, model_factory=None)`:解密 Key→`factory.build`→`probe()`→回写 `last_tested_at`;401/403→`set_status(invalid)`+`commit`+抛 `ProviderAuthFailed`(design D7)。`model_factory` 可注入(测试用 FakeTextModel,生产用默认 `llm_factory.build`)
- [x] 6.4 超时/重试/限流:`_probe_with_retry` 仅对 `RateLimited` 有限重试(`_MAX_PROBE_ATTEMPTS=2`),鉴权错/降级直接冒泡;探测本体 `_probe.py` 短超时(10s)+ 状态映射;不无限阻塞(design D6/D7)。M1 不退避,M2 引入指数退避
- [x] 6.5 预留 `require_active_text(user_id)`:无 active 文本配置→抛 `ModelNotConfigured`(为 M2 分析门禁预留,本期不被调用,已测)
- [x] 6.6 事务边界在 service(承接 M0 D14):每用例内显式 `commit`;`get_session` 仅 yield,repo 只 flush 不 commit
- [x] 6.7 验证:`cd backend && uv run pytest tests/unit/test_model_config_service.py`(Fake LLM 替身)覆盖 create/update/delete/activate/test + FR-C5(鉴权失败置 invalid)/限流/降级/隔离,21 用例通过

## 7. 错误码、依赖接线与路由挂载

- [x] 7.1 `core/errors.py` 增 `ModelNotConfigured`(409 `model_not_configured`)、`ProviderAuthFailed`(502 `provider_auth_failed`)、`RateLimited`(502 `rate_limited`)、`QuotaExceeded`(429 `quota_exceeded`);4 类均为 `DomainError` 子类,经既有的 `_domain_error_handler` 自动登记(MRO 最具体匹配),`_STATUS_TO_CODE` 补 429/502/503/504
- [x] 7.2 `api/deps.py`:`get_crypto() -> bytes` 依赖(读 `get_mek()`,支持测试 `override_settings`);service 据此解密/封存 API Key
- [x] 7.3 `main.py`:挂载 models 路由(`/api/me/models/...`)+ `models` Swagger tag;CORS/lifespan 不变
- [x] 7.4 验证:`create_app()` 起 app;`/openapi.json` 经 `ErrorDetail.code` 词汇含四个错误码;`ModelConfigPublic` 无 `api_key`/密文/`mek` 字段(仅 `api_key_masked`),`ds_mek` 全局 0 命中

## 8. 模型配置 API(`api/models.py`)

- [x] 8.1 `api/schemas.py`:`ModelConfigCreate`(provider 白名单经 `model_validator` 调 `validate_provider` → 422)、`ModelConfigUpdate`(purpose 不可改、`api_key` 可选)、`ModelConfigPublic`(`from_attributes`,**仅 `api_key_masked`**,明文/密文永不出现)
- [x] 8.2 `GET /api/me/models`(列表,`purpose` 可选过滤)、`GET /api/me/models/{id}`(详情),均脱敏 key
- [x] 8.3 `POST /api/me/models`(201)、`PUT /api/me/models/{id}`(按 `model_fields_set` 仅传显式字段;缺省 key 不动加密列 D8)、`DELETE /api/me/models/{id}`(query `new_active_id`,删 active 规则见 6.2,204)
- [x] 8.4 `POST /api/me/models/{id}/activate`(事务内翻转 active,D3)
- [x] 8.5 `POST /api/me/models/{id}/test`(零成本自检,不真生成;502 映射 provider_auth_failed/rate_limited)
- [x] 8.6 修改 `GET /api/me`:`text_model_configured` 取 `has_active_text(user_id)` 真实值(对齐 [`architecture §3.3`](../../../docs/tech-solution/architecture.md)、design D9)
- [x] 8.7 验证:`tests/test_models_api.py`(**注:仓库约定 HTTP 流测试置于 `tests/` 根而非 `tests/integration/`**,与 `test_auth_flow.py` 同范式)覆盖 CRUD/activate/test 正常与异常、跨用户 404、`/api/me` 标记随配置翻转,13 用例通过

## 9. 后端测试与质量门

- [x] 9.1 集成测试(`tests/test_models_api.py`):CRUD/activate/test 正常路径 + 错误路径(422 白名单、409 active 规则 `invalid_state`、502 鉴权失败→`status=invalid`)
- [x] 9.2 安全测试:断言响应不含明文 `api_key`(仅 `api_key_masked`)、脱敏格式正确(`sk-…7766`)、跨用户访问 404;明文 Key 架构上仅 `crypto.decrypt` 返回值瞬时驻内存,不入库/日志/响应
- [x] 9.3 `/api/me` 标记生命周期:配/删文本配置后 `text_model_configured` 翻转;image 配置不影响该标记(已覆盖)
- [x] 9.4 质量门:`ruff check`(全绿)、`mypy src/drama_smith tests`(48 文件 0 issue)、`pytest --cov` 92.63%(≥90%);`core/crypto` 93%、`llm/factory` 100%、`model_config_service` 97%

## 10. 前端类型与 API 客户端

- [x] 10.1 `frontend/src/types/models.ts`:`ModelConfig`/`ModelConfigCreate`/`ModelConfigUpdate`/`ModelPurpose`/`ModelStatus` + 三类 `Text/Image/VideoProvider` 白名单并集 `Provider`(取自 llm/base.py);`ModelConfig` 的 key 字段为脱敏串 `api_key_masked`,明文仅 `Create/Update.api_key`;`index.ts` re-export;`User.text_model_configured` 注释更新为真值(后端 `has_active_text`)。`tsc` + `eslint` 全绿
- [x] 10.2 `frontend/src/api/endpoints.ts`:新增 `modelsApi` —— `list(purpose?)/get/create/update/delete(id,newActiveId?)/activate/test`,复用 M0 的 `request` 封装(401 自动刷新拦截内建、204 → null)。`tsc` + `eslint` 全绿

## 11. 前端配置向导 + 设置页

- [x] 11.1 `features/ai-config/Wizard.tsx`:三步向导(文本必配 + 自检通过方继续;图片/视频可跳过);`ModelConfigForm`(RHF + Zod,provider 白名单校验对齐后端);`providers.ts` 白名单目录 + 选供应商默认模型预填
- [x] 11.2 `RequireAuth` 统一预加载 `user`(`/api/me`)+ `RequireSetup` 门禁:`text_model_configured===false` → 重定向 `/setup`(design D11);`/setup` 绕过门禁、已配则回主页;`auth.refreshUser` 供变更后同步标记
- [x] 11.3 `features/ai-config/ManageModels.tsx`(嵌入 `SettingsPage`):按用途分组增删改、切换生效、单条自检(视频 M3 隐藏自检)。**改用 Zustand + 本地态手动取/刷新,未引 TanStack Query**(用户裁定:与 M0 范式一致、免新依赖;偏离 task 原措辞)
- [x] 11.4 删 active 且同 purpose 有兄弟 → `DeleteSuccessorOverlay` 要求选继任(对齐 6.2 invalid_state)
- [x] 11.5 验证:`tsc` + `eslint` + `vite build`(1953 模块)全绿;端到端人工跑通(登录→向导→配文本自检→设置页增删改/切换/自检)待用户在后端在跑时验收

## 12. 联调与收尾

- [x] 12.1 前后端本地联调通路就绪:均连 env 外部 MySQL(不另起 docker-compose);后端 `uv run uvicorn drama_smith.main:app --reload`、前端 `yarn dev`;`DS_MEK` 生成 / 备份指引已入 `.env.example` + README。**端到端人工跑通(登录→向导→设置)待用户本机验收**(同 11.5)
- [x] 12.2 `backend/.env.example` 已含 `DS_MEK` + 生成 / 备份说明(1.4);根 README 补:`DS_MEK` 配置步骤与配置项表行、新增依赖 `cryptography` / `litellm` 注记、`model_configs` 迁移、BYOK `/api/me/models` 端点
- [x] 12.3 `openspec status --change setup-byok-config`:proposal / 2 specs(ai-config + user-auth)/ design / tasks 工件齐备;实施完成,待 `/opsx:archive`
