## ADDED Requirements

### Requirement: 角色形象图可由用户上传

系统 SHALL 提供 `POST /api/episodes/:episode_id/characters/:character_id/image/upload`(`multipart/form-data`,字段 `file`),把用户上传的图片作为该剧集角色的形象图落库并展示(对齐 [FR-L4](../../../../docs/requirements/features/character-library.md) 上传约束、[`analysis §5.2`](../../../../docs/requirements/features/analysis.md) 形象参考)。系统 SHALL 仅接受 `image/{jpeg,png,webp}`;其它类型拒绝。系统 SHALL 用 Pillow 解码并取宽高;**落盘字节超过 1 MiB 时必须重新压缩至 ≤ 1 MiB**(JPEG 递降质量)。系统 SHALL 经 `FileStore` 落盘、落 `media` 行(`kind='image'`、`source='upload'`、`selected=true`、`owner_type='character'`、`owner_id=character_id`、`user_id`、`content_type`/`size_bytes`/`width`/`height`)、把同 `(user_id, owner_type, owner_id)` 的旧 media 翻 `selected=false`、并更新 `episode_characters.image_media_id` 指向新行;成功返回 201 + 当前形象图视图(`media_id`/`signed_url`/`content_type`/`width`/`height`)。

#### Scenario: 上传有效图片成功并成为当前形象图
- **WHEN** 已认证用户对其拥有、`appearance_desc` 可空的剧集角色发起 `POST .../image/upload`,body 为合法 JPEG
- **THEN** 系统返回 201,响应 `data` 含 `media_id`、`signed_url`(可被 `<img>` 直接渲染)、`content_type='image/jpeg'`、`width`/`height`;`media` 行 `source='upload'`、`selected=true`、`owner_type='character'`;角色 `image_media_id` 指向该行

#### Scenario: 超过 1 MiB 的图片被压缩至限额内
- **WHEN** 上传 3 MiB 的 PNG
- **THEN** 系统 SHALL 用 Pillow 重新压缩,落盘字节 ≤ 1 MiB,`media.size_bytes` 反映压缩后大小,请求成功(201),不被拒绝

#### Scenario: 拒绝非图片内容类型
- **WHEN** 上传 `image/svg+xml` 或 `application/octet-stream`
- **THEN** 系统返回 422(`validation_error` 或 `invalid_state`),不落盘、不写 `media` 行、不改 `image_media_id`

#### Scenario: 越权访问不泄露存在
- **WHEN** 已认证用户对他人剧集 / 他人角色(或不存在)的 id 发起上传
- **THEN** 系统返回 404(`not_found`),不泄露资源存在性

### Requirement: 角色形象图可由 AI 异步生成

系统 SHALL 提供 `POST /api/episodes/:episode_id/characters/:character_id/image/generate`(`application/json`,无 body 或可选 style 提示),发起角色形象图的 AI 生成。该端点 SHALL 为**异步任务**:同步校验门禁后创建 `tasks.type='image'`、`status='pending'` 的任务并 202 返回 `TaskPublic`;真实生成在后台 work 闭包内执行(构 `ImageModel` → `generate(prompt)` → 下载远程图 → 落盘 → 落 `media` + 更新 `image_media_id`),前端经 `GET /tasks/:id` 轮询。系统 SHALL 在发起前强制两道门禁:(1) 用户有 active 且 `status='active'` 的 image 模型配置,否则 `model_not_configured`(409);(2) 角色已填 `appearance_desc`(非空白),否则 `invalid_state`(409,details `reason='appearance_required'`)。生成 prompt SHALL 以 `appearance_desc` 为主、辅以 `name`/`role_type`/`persona`;prompt 构造留在 `services/character_media_service.py`(不进 `analysis/`/`graphs/`/`tasks/`,守 NFR-2)。生成成功的新 `media` 行 `source='generate'`、`selected=true`,旧形象图翻 `selected=false` 并保留。任务 `output_refs` SHALL 含 `{media_id}`。

#### Scenario: 满足门禁时异步发起并终态产出形象图
- **WHEN** 已认证用户对自有、已填 `appearance_desc` 的角色发起生成,且用户有 active image 配置
- **THEN** 系统返回 202 + `TaskPublic`(`type='image'`、`status='pending'`);后台 work 调用 `ImageModel.generate` 得远程图、下载落盘、写 `media`(`source='generate'`、`selected=true`)、更新 `image_media_id`;任务转 `succeeded`,`output_refs` 含 `media_id`;后续 `GET .../image` 返回该形象图

#### Scenario: 无 active image 配置时拒绝
- **WHEN** 用户无 active image 模型配置(或仅 `status='invalid'`)时发起生成
- **THEN** 系统返回 409 `model_not_configured`,不创建任务、不调 LLM

#### Scenario: 角色未填形象描述时拒绝
- **WHEN** 角色 `appearance_desc` 为空 / 纯空白时发起生成(即便已配 image 模型)
- **THEN** 系统返回 409 `invalid_state`(details `reason='appearance_required'`),不创建任务、不调 LLM

#### Scenario: 越权访问不泄露存在
- **WHEN** 已认证用户对他人剧集 / 角色发起生成
- **THEN** 系统返回 404(`not_found`)

#### Scenario: 生成失败可重试不挂起
- **WHEN** 后台 `ImageModel.generate` 抛 `RateLimited`(限流/超时耗尽重试)或返回不可解析/非图片字节
- **THEN** 任务转 `failed`(`error.code` 为 `rate_limited` 或 `internal_error`),不落损坏文件、不改 `image_media_id`;前端可重发

### Requirement: 当前角色形象图可读取

系统 SHALL 提供 `GET /api/episodes/:episode_id/characters/:character_id/image`,返回该角色当前选用(`selected=true` 且 `image_media_id` 指向)形象图的展示视图(`media_id`、`signed_url`、`content_type`、`width`、`height`、`source`)。无形象图时返回 **204**(无 body)。`signed_url` SHALL 是短期有效的 `GET /api/media/:media_id/content` 鉴权链接,可被 `<img src>` 直接使用。

#### Scenario: 已有形象图时返回展示视图
- **WHEN** 角色已设形象图,已认证用户(属主)请求 `GET .../image`
- **THEN** 系统返回 200,`data` 含 `media_id`、`signed_url`、`content_type`、`width`、`height`、`source`

#### Scenario: 无形象图时返回 204
- **WHEN** 角色 `image_media_id` 为 NULL
- **THEN** 系统返回 204(无响应体),前端据此显示占位头像

#### Scenario: 越权访问不泄露存在
- **WHEN** 已认证用户对他人剧集 / 角色请求
- **THEN** 系统返回 404(`not_found`)

### Requirement: 富媒体经本地 FileStore 落盘并以签名 URL 下发

系统 SHALL 经 `FileStore` 抽象(`storage/base.py` Protocol + `storage/local.py` `LocalFileStore` 实现)持久化媒体字节,落盘路径为 `<DS_MEDIA_ROOT>/<user_id>/<yyyy>/<mm>/<uuid>.<ext>`,`storage_key` 为相对路径并写入 `media.storage_key`;`media.storage_provider` 默认 `'local'`。系统 SHALL 以 HS256(复用 `DS_JWT_SECRET`,**不引入新密钥**)签发短期 token,payload 含 `sub=media_id` 与 `exp`,TTL ≤ 300 秒。系统 SHALL 提供 `GET /api/media/:media_id/content?token=&exp=`,**不要求 `Authorization` 头**,验签 + 校 `sub == 路径 media_id` + 未过期后,以正确 `content-type` 流式返回字节。

#### Scenario: 合法签名 URL 直接渲染图片
- **WHEN** 浏览器 `<img src="/api/media/123/content?token=<valid>&exp=<future>">`(无 Authorization 头)
- **THEN** 系统验签通过、`sub==123`、未过期,返回 200 + 图片字节 + 对应 `content-type`;图片正常渲染

#### Scenario: 过期 token 被拒
- **WHEN** `exp` 已过当前时间
- **THEN** 系统返回 401(`unauthenticated`),不下发字节;前端从 `GET .../image` 重取新 `signed_url`

#### Scenario: token 的 media_id 与路径不符被拒
- **WHEN** 路径为 `/api/media/124/content` 而 token `sub=123`
- **THEN** 系统返回 401(`unauthenticated`),防 token 跨媒体挪用

#### Scenario: media_root 启动期创建
- **WHEN** 后端启动(lifespan)且 `DS_MEDIA_ROOT` 目录不存在
- **THEN** 系统 SHALL `mkdir(parents=True, exist_ok=True)`;缺失权限时 fail-fast(启动报错),不静默

### Requirement: image LLM 接缝支持 OpenAI 兼容端点并映射异常 / 有界重试

`LitellmImageModel.generate`(`llm/litellm_image.py`)SHALL 与 text adapter 对齐:当 `snapshot.base_url` 给定时,SHALL 先 `normalize_base_url` 再以 `api_base` + `custom_llm_provider="openai"` 路由(否则 litellm 对陌生模型报 "LLM Provider NOT provided");无 `base_url` 时由 litellm 按 model 原生路由。SHALL 把 `AuthenticationError`(及 401/403)映射为 `ProviderAuthFailed`(**不重试**,运行期置配置 `invalid`);`RateLimitError`/`Timeout`/`APIConnectionError`/429/5xx 经 1+3 次指数退避(1s/2s/4s)重试,耗尽抛 `RateLimited`;其余 4xx 原样上浮。`probe()` SHALL 同步用规整后的 `base_url`。本要求收尾 M2 `litellm_image.py:6-8` TODO。

#### Scenario: 自定义 base_url 按 openai 路由
- **WHEN** image 配置含 `base_url`(如 SiliconFlow 托管端点)且模型名非 litellm 内置
- **THEN** `generate` 以 `custom_llm_provider="openai"` 调用,不报 "LLM Provider NOT provided";成功返回远程图 URL

#### Scenario: 鉴权失败不重试并冒泡
- **WHEN** 供应商返回 401/403(`AuthenticationError`)
- **THEN** `generate` 立即抛 `ProviderAuthFailed`(不重试),后台 work 据此把 image 配置置 `invalid`

#### Scenario: 限流/超时经有界重试后冒泡
- **WHEN** 供应商持续返回 429 或超时
- **THEN** `generate` 经 1+3 次指数退避后抛 `RateLimited`(任务 `failed`,`error.code='rate_limited'`)

#### Scenario: 原生 provider 无 base_url 正常路由
- **WHEN** image 配置无 `base_url`(如官方 OpenAI 模型名)
- **THEN** `generate` 不设 `custom_llm_provider`,由 litellm 按 model 路由,成功返回图 URL

### Requirement: image 模型配置门禁

`model_config_service` SHALL 提供 `require_active_image(session, user_id)`:取该用户 active 且 `status='active'` 的 image 配置,无则抛 `ModelNotConfigured`(409);`build_image_model_from_config(config, mek)` SHALL 解密 Key(明文仅驻返回 adapter 内存)、经 `factory.build` 构造 `ImageModel`。发起 AI 生成时 service SHALL 先 `require_active_image` 取配置行、work 闭包捕获**冻结的**配置行(运行期用户改 active 配置不影响在途任务,镜像 text 的 D9)。`model_config_repo` SHALL 补 `get_active_image_config`(镜像 `get_active_text_config`)与 `has_active_image`(供 `/api/me` 完成度信号)。

#### Scenario: 无 active image 配置拒绝生成
- **WHEN** 用户无 active image 配置(或仅 `status='invalid'`),`require_active_image` 被调用
- **THEN** 抛 `ModelNotConfigured`(409)

#### Scenario: 被判 invalid 的配置不可用于生成
- **WHEN** image 配置存在且 `is_active=true` 但 `status='invalid'`
- **THEN** `require_active_image` 视同未配置,抛 `ModelNotConfigured`(409)

#### Scenario: 在途任务冻结配置不受运行期切换影响
- **WHEN** image 生成任务在途时,用户切换 active image 配置
- **THEN** 在途任务的 work 闭包仍用发起时捕获的配置行(冻结),不受切换影响;新发起的生成用新 active 配置

### Requirement: 多租户隔离与旧形象图保留

所有 `media` 读写 SHALL 强制 `user_id` 过滤,越权访问他人 media → 404(不泄露存在性)。`media` 表 SHALL 横切带 `user_id` 列 + `(user_id, owner_type, owner_id)` 复合索引。生成 / 上传新形象图时,系统 SHALL 把同 `(user_id, owner_type='character', owner_id)` 的旧 media 翻 `selected=false` **但保留行与磁盘文件**(本期不删、不暴露历史 UI,D9);删除角色时,其 `media` 行保留(`shot_characters` 既有 CASCADE 不受影响)。

#### Scenario: 越权读写他人 media 返回 404
- **WHEN** 已认证用户 A 尝试读 / 上传 / 生成到用户 B 的剧集 / 角色 / media id
- **THEN** 系统返回 404(`not_found`),不泄露存在性;`user_id` 过滤在仓储层兜底

#### Scenario: 重新生成形象图时旧图保留并取消选用
- **WHEN** 角色已有形象图 M1(`selected=true`),用户再次生成得 M2
- **THEN** M2 `selected=true` 且 `image_media_id` 指向 M2;M1 `selected=false` **但行与磁盘文件保留**;`GET .../image` 返回 M2

#### Scenario: 删除角色不影响既有 media 行
- **WHEN** 删除一个已配形象图的角色
- **THEN** `episode_characters` 行删除(`shot_characters` FK CASCADE 清出场引用);该角色的 `media` 行与磁盘文件保留(D9,留待 M4+ 清理)
