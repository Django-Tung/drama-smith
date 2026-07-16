## Why

M2(`setup-structured-analysis`)已把 drama-smith 走通「剧本 → 预置/拆解角色 → 结构化拆解 → 可编辑分镜」,但**角色至今没有形象图**——`episode_characters.image_media_id` 在 M2 被显式推迟(`backend/src/drama_smith/db/models/episode_characters.py:40` 的 `TODO(M3)`),`media` 表、`storage/FileStore`、image LLM 真实调用路径全部未建。用户无法为角色配可视化形象,而「形象参考」正是后续单镜素材一致性生成(FR-A7)、跨镜角色一致性的前提([`analysis §5.2`](../../../docs/requirements/features/analysis.md))。本变更落地里程碑 **M3 的第一刀:角色形象图**——支持**用户上传**与 **AI 异步生成**两种来源,落地 docs 已蓝图的 `media` 表 + 本地磁盘 `FileStore` + 鉴权签名 URL 下发([`backend.md §8`](../../../docs/tech-solution/backend.md) / [`architecture §5.6`](../../../docs/tech-solution/architecture.md)),并**首次真实调用 image LLM 接缝**(M1 仅留 Protocol + `probe()`,`LitellmImageModel.generate()` 有未修缺陷,`litellm_image.py:6-8` TODO)。承接 M0/M1/M2 地基,为 M3 后续(单镜素材 FR-A7、成片)提供富媒体底座。

## What Changes

- **新增 `media` 表**(富媒体统一元数据表,对齐 [`database.md §3.7`](../../../docs/tech-solution/database.md)):`user_id` / `kind`(`image`/`video`/`final`) / `owner_type`(`shot`/`character`/`library`/`episode`) / `owner_id` / `source`(`upload`/`generate`) / `storage_provider`(默认 `'local'`) / `storage_key` / `content_type` / `size_bytes` / `width` / `height` / `duration_sec` / `selected` / `status` + 时间戳;横切表带 `user_id`(归属校验);`(user_id, owner_type, owner_id)` 复合索引覆盖多态归属,不为 `owner_id` 单独建索引([`database.md`](../../../docs/tech-solution/database.md) 索引权衡)。
- **`episode_characters` 加 `image_media_id`**(BIGINT UNSIGNED NULL,对齐 [`database.md:115/177`](../../../docs/tech-solution/database.md)):指向当前选用形象图 media 行;**逻辑指针,不加物理外键**(避免循环依赖,与 M2 `episodes.current_analysis_id` 同构),归属由应用层把关。本期 `source` ENUM 不扩(仍 `preset`|`analysis`;`library` 值与 `source_library_id` 列随 M4)。
- **新增 `storage/` 包**(对齐 [`backend.md §8`](../../../docs/tech-solution/backend.md)):`base.py`(`FileStore` Protocol:`save` / `read` / `sign_url` / `delete`)+ `local.py`(`LocalFileStore`,落盘 `<media_root>/<user_id>/<yyyy>/<mm>/<uuid>.<ext>`,`storage_key` = 相对路径,`sign_url` → 短期签名下载 URL)。`core/config.py` 增 `media_root` 字段(已规划,[`backend.md:255`](../../../docs/tech-solution/backend.md))。本期仅 local 实现,预留对象存储接缝([`architecture §5.6`](../../../docs/tech-solution/architecture.md))。
- **新增 Alembic 迁移**(`down_revision = c4a1f9e20b7d`,M2 HEAD):`op.create_table('media', ...)` + `op.add_column('episode_characters', image_media_id)`;项目**首个 `add_column` 迁移**(既有全是 `create_table`)。
- **修复 image LLM 接缝(`llm/litellm_image.py`)**:抄 text adapter 已修范式——补 `custom_llm_provider="openai"` + `normalize_base_url`(当 `base_url` 给定时)、`AuthenticationError`→`ProviderAuthFailed`(不重试)、`RateLimitError`/`Timeout`→有限重试(1+3 次指数退避 1/2/4s);同步修 `probe()` 的 `base_url` 路由。清账 M2 `litellm_image.py:6-8` TODO。
- **`model_config_service` 增 image 门禁**(镜像 text):`require_active_image(user_id)`(无 active image 配置 → `ModelNotConfigured`)+ `build_image_model_from_config(...)`(解密 Key 仅驻内存 → `factory.build` → `ImageModel`)。
- **新增 image 异步任务 + service**:`tasks.type='image'`(ENUM 已含,M2 预留)复用执行器;新 `character_media_service`:`generate_portrait`(异步:门禁 image 配置 + 角色已填 `appearance_desc` → 建 task → `executor.submit` → work 闭包内构 `ImageModel` → `generate(prompt)` 得**远程临时 URL** → `httpx` 下载到 `FileStore` → 落 `media`(`selected=true`)+ 更新 `character.image_media_id`)+ `upload_portrait`(同步:`multipart` → Pillow 校验/压缩 ≤1MB → `FileStore.save` → 落 media + 更新指针)+ `get_portrait`(取当前形象图 + 签名 URL)。
- **新增角色形象图 API**(REST,Bearer + 强制隔离,对齐 [`architecture §3.3`](../../../docs/tech-solution/architecture.md) 行 130):`POST /api/episodes/:id/characters/:cid/image/upload`(同步 multipart,≤1MB 超限压缩)、`POST /api/episodes/:id/characters/:cid/image/generate`(异步 image 任务,202)、`GET /api/episodes/:id/characters/:cid/image`(返回当前形象图 `{media_id, signed_url, content_type, width, height}` 或 204 无)、`GET /api/media/:media_id/content?token=...&exp=...`(短期签名鉴权下发字节,`<img src>` 直用,无需 Authorization header)。把 docs 行 130 的合一端点拆为 upload/generate 两条:上传同步 multipart、生成异步任务,语义不同故分开(见 design)。
- **前端**:角色卡片增头像展示 + 「上传图片」(原生 `<input type=file>` + `FormData`,`client.ts` 通道已就绪)/「AI 生成」(发起 image 任务 + 复用 `useTaskPolling` 轮询)按钮;`EpisodeCharacter` 类型扩形象图字段;新增轻量 Avatar(无 shadcn Avatar 原语,**自建**);门禁:无 active image 配置或角色缺 `appearance_desc` 时禁用「AI 生成」并提示;图片经签名 URL `<img>` 渲染。复用 M2 Zustand + `request()` + 轮询范式,**不引新前端依赖**。
- **新增依赖**:后端 +`Pillow`(图片解码 / 取尺寸 / 压缩 ≤1MB,[FR-L4](../../../docs/requirements/features/character-library.md))+ `httpx`(下载远程生成图;若已在依赖树则复用);前端无新增运行时依赖。

## Capabilities

### New Capabilities

- `character-media`:围绕「角色形象图」落地富媒体底座——`media` 统一元数据表 + 本地磁盘 `FileStore`(鉴权签名 URL 下发)+ 角色形象图两种来源(用户上传同步 / AI 生成异步 image 任务);首次真实调用 image LLM 接缝(修 adapter 缺陷);门禁(image BYOK 配置 + 角色已填形象描述);上传 ≤1MB 超限压缩;`EpisodeCharacterPublic` 扩只读形象图字段(`image_media_id` + 派生展示信息,形象图读取由本能力 own)。需求条目对齐 [`analysis §4.2/§5.2`](../../../docs/requirements/features/analysis.md) 形象参考、[`architecture §5.6`](../../../docs/tech-solution/architecture.md) 富媒体访问、[FR-L4](../../../docs/requirements/features/character-library.md) 上传约束。**单镜素材(FR-A7)、成片/视频、库角色形象图(FR-L4 的 `/api/me/characters/...`)**均 Non-Goal,本期仅剧集角色形象图 + `media`/`FileStore` 底座。

### Modified Capabilities

- 无。M2 `analysis` 能力的既有 SHALL 行为(角色 CRUD / 拆解 / 分镜)**零改动**;`EpisodeCharacterPublic` 仅**叠加**形象图只读字段,归属 `character-media` 能力(纯加性,按 OpenSpec 语义归入 ADDED,不作 MODIFIED delta)。

## Impact

- **代码**:
  - 后端新增 `db/models/media.py`(+ `db/models/__init__.py` re-export)、`db/repositories/media_repo.py`、`storage/{base,local}.py`、`services/character_media_service.py`;`services/model_config_service.py`(+ `require_active_image` / `build_image_model_from_config`);`api/characters.py`(+ image 子路由)、新 `api/media.py`(签名下发端点);`api/schemas.py`(+ `MediaPublic`、`EpisodeCharacterPublic.image_media_id`);`db/models/episode_characters.py`(+ `image_media_id`);`llm/litellm_image.py`(修缺陷);`core/config.py`(+ `media_root`);`main.py`(挂 media router + lifespan 构造 `LocalFileStore` 注入 `app.state.file_store` 与 `executor`)。**`episode_character_repo._CHARACTER_FIELDS` 不加 `image_media_id`**——image 专经 service 方法改,不走通用 update 白名单(见 design)。
  - `tasks/executor.py`:**构造签名不变**——`FileStore` 经 image work 闭包捕获注入(service 装配,与 `mek`/冻结 config 同范式),executor 保持「业务无感」;仅更新 docstring 收回「M3 扩展构造签名」臆测(见 design D4)。
  - 前端:`types/drama.ts`(`EpisodeCharacter.image` + `MediaPublic` + `TaskType` 增 `'image'`)、`api/endpoints.ts`(`charactersApi.uploadImage/generateImage/getImage` + `mediaApi`)、`features/episode/{CharacterGroup,CastTab,CharacterForm}.tsx`(头像展示 + 上传 + AI 生成发起/轮询 + 门禁)、新增 `components/ui/avatar.tsx`(轻量自建,无 Radix 依赖)。
- **API**:新增角色形象图端点(upload 同步 / generate 异步 / get)+ 签名下发 `GET /api/media/:media_id/content`;均 Bearer + 强制 `user_id` 隔离;签名 token = HS256(`media_id` + `exp`,用现有 `jwt_secret`)。
- **数据库**:新增 `media` 表 + `episode_characters.image_media_id` 列 + Alembic 迁移;复用 M0 ORM 约定(BIGINT UNSIGNED PK、utf8mb4、`DATETIME(3)` naive-UTC、naming_convention)。外部 MySQL 8.0.46(@122.152.235.192)`drama_smith` 库,`alembic upgrade head` 应用。
- **依赖**:后端 +`Pillow`、+`httpx`(若未在依赖树);前端无新增。新增 env `DS_MEDIA_ROOT`(默认 `./media`,生产挂载卷)。
- **文档**:实施依据 [`docs/tech-solution/`](../../../docs/tech-solution/) 的 `database.md §3.5/§3.7`、`backend.md §8`、`architecture.md §3.3(行 130)/§5.6`,需求 [`analysis.md §4.2/§5.2`](../../../docs/requirements/features/analysis.md)、[`character-library.md FR-L4`](../../../docs/requirements/features/character-library.md)(上传约束部分);本变更为 M3 切片(角色形象图)。**文档同步(apply 阶段)**:若实施出现偏离(端点拆分、`selected` 多候选简化、签名方案),收尾回写对应章节。
