## Why

drama-smith 采用 **BYOK**(用户自带模型凭证):不依赖平台统一密钥,每个用户自行配置文本 / 图片 / 视频三类模型。在叠加结构化分析(M2)等依赖模型调用的里程碑之前,必须先让用户**能安全地配置、切换、自检**自己的模型凭证——这是后续所有 LLM 调用的前置门禁,也是「凭证安全」(NFR-8)与「供应商无关单一接缝」(NFR-2)的第一处真正落地。本变更为里程碑 **M1**,承接 M0(`setup-user-foundation`)已建好的用户与会话地基。

## What Changes

- **新增 `model_configs` 表**(`backend/src/drama_smith/db/models/model_configs.py`):字段对齐 [`database.md §3.2`](../../../docs/tech-solution/database.md) —— `purpose`(text/image/video)、`provider`、`model`、`base_url`、`api_key_ciphertext`/`api_key_iv`/`dek_ciphertext`(信封加密三列)、`params`/`provider_options`(JSON)、`is_active`、`status`(active/invalid)、`last_tested_at`;以 **MySQL 生成列 `active_key` + 唯一索引**保证「每用户每用途恰一条 active」。
- **新增 `core/crypto.py` 信封加密原语**(`encrypt`/`decrypt`,AES-256-GCM,每配置一个 DEK、DEK 经 MEK 封存),对齐 [`backend.md §9`](../../../docs/tech-solution/backend.md) 与 [`database.md §6`](../../../docs/tech-solution/database.md);MEK 经环境变量(`DS_MEK`)注入、不入库/日志/OpenAPI。
- **新增 `core/llm` 供应商无关接缝**(`llm/base.py`、`llm/factory.py`、`litellm_text.py`/`litellm_image.py` + `adapters/`):`text`/`image` 经 litellm,`video` 预留自定义适配器位;构造时解密 Key(仅驻内存);对接 [`backend.md §6`](../../../docs/tech-solution/backend.md)。
- **新增模型配置 API**:`GET/POST /api/me/models`、`PUT/DELETE /api/me/models/:id`、`POST /api/me/models/:id/activate`、`POST /api/me/models/:id/test`(零成本连通性自检、不真生成);Key 列表脱敏(`sk-…ab12`),明文永不回显/落日志。
- **修改 `GET /api/me`**:`text_model_configured` 由 M0 恒 `false` 改为**真实反映**该用户是否已有 active 文本配置(作为 FR-C1 首次强制配置的完成度信号)。
- **新增错误码**:`model_not_configured`(409)、`provider_auth_failed`(502,并标 `status=invalid`)、`rate_limited`(502)、`quota_exceeded`(429),对齐 [`backend.md §10`](../../../docs/tech-solution/backend.md)。
- **新增前端配置向导 + 设置页**:首次登录(文本未配置)走强制向导(必配文本、自检通过方可继续;图片/视频可跳过);设置页做配置增删改、每类用途切换当前生效模型;复用 M0 的 REST 客户端(401 自动刷新)与 TanStack Query。

## Capabilities

### New Capabilities

- `ai-config`: 用户自带模型凭证(BYOK)的三类模型(text/image/video)配置 CRUD、每用途「当前生效」切换、零成本连通性自检、API Key 信封加密与脱敏展示;文本模型首次登录强制配置、图片/视频可选(未配则相应功能由门禁禁用)。需求条目对齐 [`docs/requirements/features/ai-config.md`](../../../docs/requirements/features/ai-config.md) FR-C1~C6。

### Modified Capabilities

- `user-auth`: `GET /api/me` 的 `text_model_configured` 字段由「M0 恒 false」改为真实反映当前用户是否已配置 active 文本模型(从 M1 起承载 FR-C1 的完成度信号)。

## Impact

- **代码**:
  - 后端新增 `core/crypto.py`、`core/llm/`(base/factory/litellm_text/litellm_image/adapters)、`db/models/model_configs.py`、`db/repositories/model_config_repo.py`、`services/model_config_service.py`、`api/models.py`;修改 `api/me.py`、`core/config.py`(增 `ds_mek` SecretStr)、`core/errors.py`(增模型类错误码与映射)、`main.py`(挂载 models 路由、`app.state.crypto` 注入)、`db/models/__init__.py`(re-export `ModelConfig`)。
  - 前端新增配置向导(`features/ai-config/Wizard`)、设置页(`routes/settings`)、`api/endpoints.ts` 的 models 段、TanStack Query hooks;修改登录后重定向逻辑(文本未配 → 向导)。
- **API**:新增 `GET/POST/PUT/DELETE /api/me/models`、`POST /api/me/models/:id/activate`、`POST /api/me/models/:id/test`;`GET /api/me` 返回体新增/激活 `text_model_configured` 真实值。契约见 [`docs/tech-solution/architecture.md §3.3`](../../../docs/tech-solution/architecture.md)。
- **数据库**:新增 `model_configs` 表(含生成列 `active_key` + 唯一索引);新增 Alembic 迁移;复用 M0 的 `users.id` 外键与隔离范式。
- **依赖**:后端新增 `cryptography`(AES-GCM)、`litellm`(文本/图片接缝);前端无新增运行时依赖。环境变量新增 `DS_MEK`(base64 32B 主密钥)。
- **文档**:实施依据为 [`docs/tech-solution/`](../../../docs/tech-solution/) 的 `database.md §3.2/§6`、`backend.md §6/§8~10`、`architecture.md §3.3/§4.2`、`frontend.md` 设置页段,以及需求 [`docs/requirements/features/ai-config.md`](../../../docs/requirements/features/ai-config.md);本变更为 M1 切片。
