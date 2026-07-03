## Context

drama-smith 已在 M0(`setup-user-foundation`)落地多用户地基:FastAPI 分层骨架、MySQL + SQLAlchemy 2.0(async)+ Alembic、注册/登录/登出/刷新、`GET /api/me`(其中 `text_model_configured` 恒为 `false`)、仓储层「强制 `user_id` 过滤」隔离范式。本变更(M1)在该地基上落地 **BYOK**:用户自配 text/image/video 三类模型凭证,做 CRUD、每用途切换「当前生效」、零成本连通性自检、API Key 信封加密,并把 `/api/me` 的完成度标记接通为真实值。

**当前状态**:后端已有 `core/{config,security,errors}.py`、`db/{base,session,models/{users,refresh_tokens},repositories}`、`services/auth_service`、`api/{auth,me,deps,schemas,health}`;前端已有 Vite+React+TS 骨架与 auth 流。本变更新增 `core/crypto.py`、`core/llm/`(接缝)、`model_configs` 表与迁移、模型配置 API、前端配置向导/设置页。

**约束(承接)**:供应商无关单一接缝(NFR-2,见 [`backend.md §6`](../../../docs/tech-solution/backend.md))、凭证安全(NFR-8,见 [`database.md §6`](../../../docs/tech-solution/database.md) / [`backend.md §9`](../../../docs/tech-solution/backend.md))、多租户强制 `user_id` 隔离与越权 404(承接 M0 D6)。需求侧条目见 [`docs/requirements/features/ai-config.md`](../../../docs/requirements/features/ai-config.md) FR-C1~C6。

## Goals / Non-Goals

**Goals:**

- `model_configs` 表(含 `active_key` 生成列 + 唯一索引)与 Alembic 迁移,字段对齐 [`database.md §3.2`](../../../docs/tech-solution/database.md)。
- `core/crypto.py` 信封加密原语(AES-256-GCM,MEK 经 `DS_MEK` 注入),明文永不落库/日志/响应。
- `core/llm` 供应商无关接缝(text/image 经 litellm,video 预留自定义适配器位),构造时仅内存解密。
- 模型配置 CRUD + activate + 零成本自检 API,Key 列表/详情脱敏。
- `GET /api/me` 的 `text_model_configured` 接通真实值,作为前端「首次强制配文本」门禁的信号。
- 错误码 `model_not_configured`/`provider_auth_failed`/`rate_limited`/`quota_exceeded` 与全局异常映射。
- 前端首次配置向导(必配文本、自检通过方可继续;图片/视频可跳过)+ 设置页增删改与切换。

**Non-Goals:**

- **真正的模型调用 / 结构化分析 / 分镜视频流水线**(FR-A,属 M2+)。本期只做「配置与自检」;`core/llm` 接缝在本期只被**自检**调用,分析图(M2)才首次真实调用文本模型。
- **首次强制配置的「服务端硬阻断」**:本期门禁以「`text_model_configured` 信号 + 客户端向导」实现;后端不在本期对分析类端点抛 `model_not_configured`(那些端点 M2 才存在)。后端只如实上报完成度。
- **视频适配器的具体供应商实现**:本期只落 `adapters/` 抽象位与协议(`submit`/`poll`),不接具体视频供应商(随 M3 首批接入定,见 [`backend.md §12`](../../../docs/tech-solution/backend.md))。
- **任务执行器 / `FileStore` / WebSocket `/ws/tasks`**(M2/M5 引入)。自检是同步短请求,不走任务执行器。
- **MEK 轮换工具 / KMS 接入**:本期 `DS_MEK` 单一 env 注入;轮换与 KMS 留待生产化(预留解封重封的接口形状)。
- **并发上限 / 配额计费**(M2+ 成本门);`quota_exceeded` 错误码本期定义但执行器未上,暂不触发。

## Decisions

**D1 信封加密用 `cryptography` 的 `AESGCM`,每配置一 DEK、DEK 经 MEK 封存;列布局裁定为「两个自包含 blob + 一列脱敏」(A2+m2)。** `encrypt()`:`os.urandom(32)` 生 DEK → DEK 经 AES-256-GCM 加密明文 Key → DEK 经 MEK 加密封存;`decrypt()` 反向,明文仅驻内存。

**列布局裁定(A2)**:GCM 双层解密需 4 份信息(key 层 `nonce₁`+`ct₁‖tag₁`、DEK 层 `nonce₂`+`ct₂‖tag₂`)。原 [`database.md §3.2`](../../../docs/tech-solution/database.md) 三列(`api_key_ciphertext`/`api_key_iv`/`dek_ciphertext`)中 **DEK 层 nonce 无家可归**——按 [`backend.md §9`](../../../docs/tech-solution/backend.md) 伪码 `dek_ct = aes_gcm_encrypt(mek, dek)` 会丢弃返回的 iv,字面实现则 `decrypt` 必败。故改为**两个对称自包含 blob**,各为 `nonce(12)‖ct‖tag(16)`:`api_key_ciphertext`(DEK 封 key)、`dek_ciphertext`(MEK 封 DEK);**删除 `api_key_iv`**。`crypto.py` 以单一 `_seal(key,data)/_open(key,blob)` helper 跑两遍,与 KMS 信封惯例一致、少一条代码路径。轮换(换 MEK 只重封 `dek_ciphertext`)与 PUT 换 key(新 DEK→两 blob 重封)语义不变。

**脱敏展示裁定(m2)**:`Masked Key Display` 要求 GET/LIST 回显 `sk-…ab12`,但明文不落库。新增 `api_key_masked VARCHAR(32)`(POST 时 `mask_key` 落库、读时直出),读路径**不碰 MEK、不解密**;所存即本就显示之串,零额外泄露。MEK = `base64.b64decode(settings.mek)`(32B;env `DS_MEK`),`SecretStr`、不入 OpenAPI/日志。对齐 [`backend.md §9`](../../../docs/tech-solution/backend.md) 伪码与 [`database.md §6`](../../../docs/tech-solution/database.md)。*替代*:① `Fernet`(简单但无独立 DEK/MEK 分层,轮换与「DEK 落库」语义弱,偏离 database.md §6 的三列设计);② 全库单一 MEK 直加密明文(无信封,MEK 泄露即全暴露,且无 DEK 轮换面);③ Tink/aso(过重,本期单实例无必要)。选信封为兼顾「MEK 不入库、每配置独立 DEK、轮换只重封 DEK 不动密文」。*替代(列布局)*:④ A1 非对称(保三列、`dek_ciphertext` 打包 nonce)——两层形状不一、无密码学理由;⑤ A3 派生 nonce(nonce₂ 由 id 派生)——insert 时无 id、耦合 DB 自增、非标;⑥ A4 复用单 nonce 喂两层——密码学上成立(两 key 不同故安全)但不变量对读列者不可见、脆。*替代(脱敏)*:⑦ m1 读时解密再 mask——合规但每次 list 过 MEK+明文驻读路径,设置页轮询下既重又违「明文最小驻留」。**文档同步(apply 阶段改源文档)**:[`database.md §3.2`](../../../docs/tech-solution/database.md)(删 `api_key_iv` 行、加 `api_key_masked` 行)、[`§6`](../../../docs/tech-solution/database.md)(blob 为自包含 `nonce‖ct‖tag`)、[`backend.md §9`](../../../docs/tech-solution/backend.md)(`Envelope(key_blob, dek_blob)` + `_seal` helper 伪码)。

**D2 MEK 经 `DS_MEK`(env,base64 32B)注入;`.env.example` 给生成指引,运行期校验长度。** `core/config.Settings.mek: SecretStr`(env `DS_MEK`),启动时若缺失或非 32B → 明确报错拒绝启动(fail-fast,避免静默落弱密钥)。*替代*:① 硬编码(违 NFR-8,否);② 启动期接 KMS(本期单实例过重,留接缝);③ 派生自 JWT secret(职责混淆、轮换耦合,否)。生产化时把「取 MEK」收敛为 `get_mek()` 一处,KMS 替换仅改此处。

**D3 「每用途恰一条 active」用 MySQL 生成列 `active_key` + `UNIQUE` 索引保证,事务内翻转。** `active_key VARCHAR(128) GENERATED ALWAYS AS (CASE WHEN is_active=1 THEN CONCAT(user_id,'-',purpose) END) VIRTUAL`,UNIQUE 索引;MySQL 允许多行 NULL(非 active 行不冲突),故天然满足「0 或 1 条 active」。`activate(id)` 在单事务内 `UPDATE ... SET is_active=0 WHERE user_id AND purpose AND is_active=1` 再 `UPDATE id SET is_active=1`。对齐 [`database.md §3.2`](../../../docs/tech-solution/database.md) 注。*替代*:① 纯应用层互斥(并发竞态,两条同时置位);② DB 触发器(可移植性差、Alembic 难管理);③ `(user_id,purpose,is_active=1)` 部分唯一索引(MySQL 不支持部分索引,故用生成列绕过)。生成列方案是 MySQL 上最干净的强约束。

**D4 「首条自动 active」与「删 active 的处理」在 service 层定。** 新建时:若该 `(user_id,purpose)` 当前 0 条 active(含 0 条配置)→ 新建行 `is_active=1`,否则 `is_active=0`(满足向导「配齐的第一条自动 active」)。删除 active 行:① 该 purpose 仍有其他配置 → 要求请求显式指定 `new_active_id`,或 409 拒绝(spec「deleting active with siblings remaining」);② 删除后该 purpose 0 条配置 → 无需处理 active(text 类回到 FR-C1 未配态;image/video 仅禁用)。对齐 [`ai-config §2.2`](../../../docs/requirements/features/ai-config.md)。*替代*:删 active 时自动挑下一条 active(隐式选择易误用,违背「用户显式指定当前生效」);本期要求显式指定,语义清晰。

**D5 `core/llm` 接缝:text/image 经 litellm,video 预留自定义适配器抽象位。** `llm/base.py` 定义 `TextModel`/`ImageModel`/`VideoModel` Protocol(`chat`/`generate`/`submit`+`poll`);`factory.py` 按 `model_configs` 快照(purpose/provider/model/明文 key/base_url/params/provider_options)构造:`text`/`image` → litellm 适配,`video` → `adapters/<provider>.py`(本期仅落抽象 + 一个「未实现」占位,M3 首批接入)。**自检**复用 `TextModel`/`ImageModel` 的零成本探测路径。对齐 [`backend.md §6`](../../../docs/tech-solution/backend.md) 与 [`architecture §4.2`](../../../docs/architecture/system-architecture.md)。*替代*:① `graphs`/`analysis` 直接 import 厂商 SDK(违 NFR-2,否);② 自写全部 HTTP(重复造轮,丢失 litellm 的供应商归一与鉴权细节);③ litellm 统管三类(litellm 对异步视频覆盖弱、协议差异大,故 video 自适应器,见 architecture §4.2)。

**D6 零成本自检策略:按 provider 走 litellm 的「列模型 / 最小 ping」,不真生成。** 文本:`litellm` 对应 provider 的零成本探测(如 OpenAI 兼容走 `models.list`、或最小非生成探测);图片:轻量 `models`/鉴权探测;**不**发起任何 `chat`/`generate`。对不支持零成本探测的 provider → 在 `provider_options` 标记或 service 层降级为「跳过并显式告知」。对齐 FR-C3。自检结果回写 `last_tested_at`、遇 401/403 → `status=invalid`。*替代*:① 最小补全/最小生成(产生真实费用,违 FR-C3,否);② 一律跳过(无校验价值,用户体验差)。

**D7 凭证失效检测(FR-C5):供应商 401/403 → 置 `status=invalid` + 抛 `ProviderAuthFailed`(→ 502)。** service/自检/后续调用捕获 provider 鉴权失败时,原子 `UPDATE model_configs SET status='invalid' WHERE id AND user_id`,再向调用方抛 `ProviderAuthFailed`(错误码 `provider_auth_failed`);客户端据此提示重新配置。本期该路径由**自检**真实触发(自检是本期唯一会调接缝的入口)。*替代*:① 仅抛错不落 `invalid`(下次自检仍盲目尝试,无状态记忆);② 落库前反复重试(鉴权错重试无意义)。

**D8 PUT 更新:`api_key` 缺省时不动加密列;给出时全量重封。** `PUT /api/me/models/:id` 的请求体 `api_key` 为 Optional:缺省 → 加密三列原样不动(不轮换 DEK、零风险);给出 → 走完整 `encrypt()` 重封三列。params/provider_options/base_url 按字段更新。对齐 spec「update without a new key preserves the existing key」。*替代*:每次 PUT 都解密再重封(无谓轮换 DEK、徒增明文驻留面)。

**D9 `GET /api/me` 完成度标记:查「该 user 是否存在 active 文本配置」单条 COUNT。** `model_config_repo.has_active_text(user_id)` → `EXISTS(SELECT 1 ... WHERE user_id AND purpose='text' AND is_active=1)`,映射 `text_model_configured: bool`。本期 `/api/me` 额外一次轻量查询可接受;后续若 `/api/me` 字段增多可缓存,本期不优化。*替代*:在 `users` 表冗余标记(双写一致性负担,否)。

**D10 复用 M0 范式:ORM 约定(D12)、事务边界在 service(D14)、错误映射。** `model_configs` 表遵守 BIGINT UNSIGNED 主键 + `user_id` FK、`__table_args__` utf8mb4、`DATETIME(3)` naive-UTC、naming_convention;`get_session` 仍只 yield 不 commit,提交在 `model_config_service` 用例边界;`ModelConfig` 在 `db/models/__init__.py` re-export(Alembic autogenerate 必需,承接 M0 D13)。新错误码(`model_not_configured` 409 / `provider_auth_failed` 502 / `rate_limited` 502 / `quota_exceeded` 429)在 `core/errors.py` 与全局异常处理器登记,对齐 [`backend.md §10`](../../../docs/tech-solution/backend.md)。

**D11 前端门禁:客户端据 `text_model_configured` 路由向导;设置页 TanStack Query 驱动。** 登录/刷新后读 `/api/me`:`text_model_configured===false` → 重定向 `/setup`(向导,必配文本、自检通过方可「进入主功能」;图片/视频步骤可跳过);`true` → 进主功能。设置页(`/settings`)用 TanStack Query 拉 `GET /api/me/models`,增删改/activate/test 走对应 mutation 并失效列表缓存。复用 M0 REST 客户端(401 自动刷新拦截)。*替代*:服务端硬阻断(本期无受阻断端点,M2 才需要,见 Non-Goals)。**本期不做服务端硬阻断**,但 service 层为 M2 预留 `require_active_text(user_id)` 抛 `ModelNotConfigured` 的可复用方法。

**D12 供应商白名单:`llm/base.py` 内按 purpose 的常量表,请求期校验。** 白名单取自 [`ai-config §2.1`](../../../docs/requirements/features/ai-config.md) 首发清单(text/image 原生+OpenAI 兼容;video 列表但本期不实现调用)。`POST/PUT` 时校验 `(purpose, provider)` ∈ 白名单,否则 422。*替代*:配置文件驱动(本期值集稳定,内联常量足够,演进时再外置)。

## Risks / Trade-offs

- **[MEK 丢失 = 全部密钥不可解]** → MEK 仅 env 注入,丢失则所有 `api_key` 不可解密。*缓解*:`.env.example` 给「生成并妥善备份 32B MEK」指引;部署文档强调 MEK 必须备份;生产化接 KMS。本期单实例 `.env` 可接受。
- **[生成列 `active_key` 的 Alembic 迁移在 MySQL 上需显式处理]** → 生成列 + UNIQUE 在 autogenerate 下易偏移、且含外键索引。*缓解*:手写/校准迁移,复用 M0 D13 的「drop_table 前删冗余 drop_index」经验;迁移在 env 配置的外部 MySQL(`DS_DATABASE_URL`)上 `upgrade`/`downgrade` 双向验证。
- **[litellm 供应商探测的「零成本」因 provider 而异]** → 部分 provider 无 `models.list` 或会触发鉴权外的副作用。*缓解*:按 provider 在 `provider_options`/适配器内声明探测能力,无零成本探测者降级跳过并显式告知(FR-C3 允许降级);自检不阻断配置保存。
- **[本期门禁仅客户端,可绕过]** → 用户可手动改路由绕过向导;但本期无受保护的分析端点(M2 才有),绕过无实际危害。*缓解*:M2 在分析 service 层落 `require_active_text` 硬门禁(本变更已预留方法)。
- **[自检调真实供应商,外部依赖可能不稳定]** → 自检联网,CI 不应打真实供应商。*缓解*:测试用 `FakeTextModel`/`FakeImageModel`(承接 [`backend.md §11`](../../../docs/tech-solution/backend.md)),自检逻辑用替身验证;真实供应商探测仅手动验收。
- **[`DS_MEK` 与 M0 既有 `.env` 共存]** → 新增 env 须并入 `backend/.env.example` 与启动说明。*缓解*:本变更任务含更新 `.env.example` 与 README 启动段。

## Migration Plan

**首次部署(M1):**

1. 生成 32B MEK:`openssl rand -base64 32`,写入 `backend/.env` 的 `DS_MEK`(并备份)。
2. 后端:`cd backend && uv sync`(新增 `cryptography`、`litellm`)→ `alembic upgrade head`(建 `model_configs` 表 + 生成列 + 唯一索引)→ 重启服务(启动校验 MEK 长度)。
3. 前端:`cd frontend && npm install`(无新依赖)→ `npm run dev`(向导/设置页随路由生效)。
4. 验证:注册新用户 → 登录被引导向导 → 配文本(自检通过)→ 进主功能 → 设置页增删改/切换/自检 → `/api/me` 的 `text_model_configured` 随配置生命周期翻转。

**回滚(仅开发期):** `cd backend && alembic downgrade <prev>` 删除 `model_configs` 表;移除 `core/llm`、`core/crypto.py`、模型配置 API 与前端向导/设置页;`/api/me` 回退为 `text_model_configured: false`(即 M0 行为)。生产走向前迁移 + 兼容期,不做破坏性回滚。

## Open Questions

- 自检的「零成本探测」:是否需要一个 `provider → probe 方法` 的显式注册表(而非散落在各 adapter)?本期按 adapter 内方法实现,若 provider 增多再抽注册表(随 M3 视频接入定)。
- `provider_options` 的字段集是否需要在 `POST` 做按 provider 的强校验(如 Azure 必填 `endpoint`/`api_version`)?本期做「开放 JSON + provider 白名单」弱校验,M2/M3 接真实供应商时再细化必填规则。
- 是否在 `/api/me` 一并返回 `image_model_configured`/`video_model_configured`?本期需求仅要求文本完成度信号(FR-C1);图片/视频门禁的 UI 信号可后续按需补,不在本变更强求。
