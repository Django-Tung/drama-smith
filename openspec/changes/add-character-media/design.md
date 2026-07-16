## Context

drama-smith M0–M2 已落地:多租户 + BYOK 地基(M0/M1)、结构化分析核心 + 可编辑分镜(M2)。但**角色没有形象图**——`episode_characters.image_media_id` 在 M2 被显式推迟(`backend/src/drama_smith/db/models/episode_characters.py:40` 的 `TODO(M3)`),富媒体底座(`media` 表、`storage/FileStore`、image LLM 真实调用)**一行未写**。当前代码事实:

- **image LLM 接缝是「声明级」未通电**:`llm/litellm_image.py:28-39` 的 `generate()` 既未按 OpenAI 兼容端点补 `custom_llm_provider="openai"` + `normalize_base_url`(text adapter 5.5 spike 修过的同款缺陷),也无 litellm 异常映射 / 有界重试——其 `TODO(M3)`(`litellm_image.py:6-8`)点名等本变更收尾。`probe()`(`litellm_image.py:41-44`)同缺陷。text adapter(`litellm_text.py:44-78`)已固化正确范式可直接照搬。
- **模型配置门禁只有 text**:`model_config_service.require_active_text`(`:262-271`)+ `build_text_model_from_config`(`:274-291`)+ `mark_config_invalid`(`:294-303`)是 M2 分析门禁范式;image 无对应方法,`model_config_repo` 也只有 `get_active_text_config`(`:157-172`)、`has_active_text`(`:145-154`)。
- **执行器「不耦合业务」**:`tasks/executor.py` 的 `Work = Callable[[ProgressCallback], Awaitable[dict | None]]`(`:26`),work 闭包由 service 注入、捕获所需业务依赖(如 `mek`/冻结 config);executor 只调度 + 写 task 记录。其 docstring(`:6-7`)曾臆测「M3 引入 media 时扩展构造签名」,但 executor 既定原则是「对业务无感」(`:9`)——FileStore 是业务依赖,不该进构造签名。
- **角色 CRUD 已就绪**:`api/characters.py` router(`/episodes` 前缀)已有 list/create/get/update/delete;`EpisodeCharacterPublic.model_validate(c)` 出 schema。形象图可作为子资源 `.../image/*` 挂在同一 router。

外部约束(全程生效):外部 MySQL 8.0.46(@122.152.235.192,库 `drama_smith`);asyncmy + cryptography;`DS_MEK`/`DS_JWT_SECRET` 经 env 注入;`python3` 被 uv 拦截 → 用 `uv run`;多租户强制 `user_id` 过滤、越权 404;services 拥事务、repos 只 flush;`analysis/`/`graphs/`/`tasks/` 不 import litellm/crypto/services(NFR-2)。本设计依据 [`docs/tech-solution/database.md §3.5/§3.7`](../../../docs/tech-solution/database.md)、[`backend.md §8`](../../../docs/tech-solution/backend.md)、[`architecture.md §3.3/§5.6`](../../../docs/tech-solution/architecture.md),需求 [`analysis.md §4.2/§5.2`](../../../docs/requirements/features/analysis.md) 形象参考、[`character-library.md FR-L4`](../../../docs/requirements/features/character-library.md) 上传约束——**不复述理由,只记本期决策**。

## Goals / Non-Goals

**Goals:**
- 角色形象图两种来源可用:**用户上传**(同步 multipart,≤1MB 超限 Pillow 压缩)与 **AI 生成**(异步 image 任务 202 + 前端轮询)。
- 落地富媒体底座:`media` 统一元数据表 + `storage/FileStore` 抽象(本地实现 + 对象存储接缝)+ 鉴权签名 URL 下发(`<img src>` 直用,免 Authorization header)。
- **首次真实通电 image LLM 接缝**:修 `litellm_image.py` 缺陷(照搬 text adapter 范式)+ 补 image 门禁(`require_active_image` / `build_image_model_from_config`)+ 真实异步生成 + 远程图下载落盘。
- 门禁可懂:AI 生成须 active image 配置 **且** 角色已填 `appearance_desc`;无配置时前端禁用按钮并引导至设置。
- 复用 M2 范式零回归:Envelope/domain-error 自动映射、executor 异步任务、`useTaskPolling` 轮询、Zustand+manual `request()`,不引新前端运行时依赖。

**Non-Goals:**
- **单镜素材生成 / 视频生成 / 成片导出**(FR-A7、M3+):`media` 表 `kind` 预留 `video`/`final`、`owner_type` 预留 `shot`/`library`,但本期不实现其生成路径——只建表 + 写 image 一条通路。
- **角色库(`/api/me/characters`)形象图**(FR-L4 库角色部分):本期只剧集角色(`/api/episodes/:id/characters/:cid/image`)。
- **多候选 picker / 形象图历史浏览**:每次生成产新 media 行(`selected=true`),旧的保留 `selected=false` 但本期不暴露 UI(见 D9)。
- **对象存储真实接入**(MinIO/S3):`FileStore` 留 Protocol 接缝,本期仅 `LocalFileStore`。
- **WebSocket 推送 image 进度**:复用 REST 轮询(`useTaskPolling`),不接 `/ws/tasks`。
- **`tasks.type` ENUM 扩容**:`'image'` 已在 M2 预留,无需迁移 ENUM。

## Decisions

### D1 — `media` 表:多态归属(`owner_type`+`owner_id`)+ `user_id` 横切隔离

**选:** 单一 `media` 表,`owner_type ∈ {shot, character, library, episode}` + `owner_id`(BIGINT)+ `kind ∈ {image, video, final}` + `source ∈ {upload, generate}`;**横切带 `user_id`**(归属校验,与所有业务表一致);`(user_id, owner_type, owner_id)` 复合索引覆盖多态归属查询,**不为 `owner_id` 单独建索引**(docs 索引权衡:多态 id 跨表无意义)。

**为什么选 X 不选 Y:**
- *替代 a(每类资源一列 FK)*:`shot_media_id` / `character_image_media_id` ……列数随资源类爆炸,且同一 media 无法被多 owner 共享。否。
- *替代 b(多态关联表 `media_owners`)*:多一张 join 表,本期只有「角色↔形象图」一种归属,over-engineering。否。
- 多态归属 + `user_id` 横切:与 docs §3.7 蓝图一致、未来加 `shot`/`library` 归属零改表结构,只加枚举值。**采纳。**

### D2 — `FileStore` 抽象 + 本地落盘 + 鉴权签名 URL

**选:** `storage/base.py` 定义 `FileStore` Protocol(`save(name, data)→storage_key` / `read(key)→bytes` / `sign_url(key, ttl)→(token, exp)` / `delete(key)`);`storage/local.py` 的 `LocalFileStore` 落盘 `<media_root>/<user_id>/<yyyy>/<mm>/<uuid>.<ext>`,`storage_key` = 相对路径;**下发经签名 URL**(`GET /api/media/:id/content?token=&exp=`,`<img src>` 直用)。

**为什么选 X 不选 Y:**
- *替代 a(直接 `GET /api/media/:id/content` 走 Bearer)*:`<img src>` 不能带自定义 header,需前端先 fetch blob 再 `URL.createObjectURL`,复杂且占内存。否。
- *替代 b(现在就接 S3 presigned URL)*:本期无对象存储账户,且 docs 明确「本地磁盘 + FileStore 抽象(可平滑切 MinIO/S3)」。先本地,留接缝。否(本期)。
- 签名 URL:复用 `jwt_secret` HS256 签 `media_id`+`exp`(见 D10),`<img src>` 零额外请求头,过期前端从 `GET .../image` 重取。**采纳。**

### D3 — `episode_characters.image_media_id` 逻辑指针,不加物理外键

**选:** `image_media_id` BIGINT UNSIGNED NULL,**不建 FK**(应用层把关归属 + 置换);`media` 行 `selected` 标当前选用;删角色 → CASCADE 清 `shot_characters`(既有),`media` 行**保留**(历史,见 D9)。

**为什么选 X 不选 Y:**
- *替代 a(FK + ON DELETE SET NULL)*:`episode_characters` 已被 `episodes.current_analysis_id` 逻辑指针范式主导(M2 D3 同构),加 FK 会引入循环依赖(`media.owner_id` 指回 character / character 又 FK 指 media)。否。
- 逻辑指针 + 应用层归属校验:与 M2 既定同构、避免 FK 环、置换形象图只是改指针不触发 FK 重整。**采纳。**

### D4 — `FileStore` 经 work 闭包捕获注入;**executor 构造签名不变**

**选:** image generate 的 work 闭包在 `character_media_service` 内构造时**闭包捕获** `file_store`(+ `mek`、冻结 config、`session_factory`、`character_id`,与 analysis work 捕获 `mek`/config 同范式);executor 的 `submit(task_id, user_id, work)` 签名 **零改动**。仅更新 `executor.py` docstring:把「M3 扩展构造签名」臆测改为「FileStore 经 work 闭包传入,executor 保持业务无感」。

**为什么选 X 不选 Y:**
- *替代(executor 构造签名加 `file_store`,即 M2 docstring 预告)*:违反 executor 既定原则「对业务无感」(`executor.py:9`)——FileStore 是业务依赖(storage backend、路径策略属业务域),塞进调度器构造函数耦合了两个域;且 `Work` 签名只收 `progress_cb`,加参也破坏既有 `analyze`/`optimize` work。否。
- 闭包捕获:`mek` 已是先例(analysis work 闭包捕获 mek + 冻结 config);FileStore 同理作为业务依赖由 service 装配进闭包,executor 仍只调度。**采纳。**(本决策修正了 proposal.md「修改 executor 构造签名」的措辞——design 为权威。)

### D5 — upload 同步 / generate 异步 image 任务

**选:** 上传走**同步**请求(multipart → Pillow 校验/压缩 → `FileStore.save` → 落 media + 更新指针 → 201);生成走**异步 image 任务**(202 + 前端 `useTaskPolling`),work 闭包内构 `ImageModel` → `generate(prompt)` → `httpx` 下载远程临时 URL → 落盘 → 落 media + 更新指针。

**为什么选 X 不选 Y:**
- *替代 a(两者都异步)*:上传是本地 CPU + 磁盘,无外部 LLM 延迟,套任务队列徒增轮询负担与 task 表噪声。否。
- *替代 b(两者都同步)*:图片生成 LLM 耗时数秒~数十秒,同步阻塞请求 → 网关超时;与 analyze/optimize 既定异步范式不一致。否。
- 混合:语义对齐延迟特征——本地操作同步、外部 LLM 异步;复用 `tasks.type='image'` + executor + 轮询,前端零新机制。**采纳。**

```mermaid
sequenceDiagram
  participant FE as 前端
  participant API as API(请求会话)
  participant SVC as character_media_service
  participant FS as LocalFileStore
  participant DB as MySQL
  participant EX as TaskExecutor(后台)
  participant LLM as ImageModel(供应商)
  participant HS as httpx

  Note over FE,API: 上传(同步)
  FE->>API: POST .../image/upload (multipart)
  API->>SVC: upload_portrait(file)
  SVC->>SVC: Pillow 解码/校验/压缩≤1MB
  SVC->>FS: save(bytes) → storage_key
  SVC->>DB: media(selected=true) + 旧 selected=false
  SVC->>DB: character.image_media_id = media.id
  SVC-->>API: MediaPublic
  API-->>FE: 201 {media_id, signed_url, ...}

  Note over FE,EX: AI 生成(异步)
  FE->>API: POST .../image/generate
  API->>SVC: generate_portrait(...)
  SVC->>SVC: require_active_image + 角色填 appearance_desc
  SVC->>DB: task(type=image, pending) + commit
  SVC->>EX: submit(task_id, work)  ;; work 闭包捕获 file_store/mek/config
  API-->>FE: 202 TaskPublic
  EX->>LLM: ImageModel.generate(prompt) → 远程 URL
  EX->>HS: GET 远程 URL → bytes
  EX->>FS: save(bytes) → storage_key
  EX->>DB: media(selected=true) + character.image_media_id
  EX-->>EX: finish(succeeded, output_refs={media_id})
  FE->>API: 轮询 GET /tasks/:id(useTaskPolling)
  API-->>FE: succeeded → 取 GET .../image(签名 URL)
```

### D6 — 端点拆 upload / generate(偏离 architecture.md 行 130 的合一端点)

**选:** `POST .../image/upload`(同步 multipart)+ `POST .../image/generate`(异步 202)+ `GET .../image`(当前形象图或 204)三条,而非 docs 行 130 草拟的单条 `POST .../image`。

**为什么选 X 不选 Y:**
- *替代(单 `POST .../image`,body 带 `source` 区分)*:upload 需 `multipart/form-data`、generate 需 `application/json`,二者媒体类型互斥,FastAPI 单端点混用易出 422 与 OpenAPI 文档混乱;且同步 201 与异步 202 状态码语义不同。否。
- 拆三端点:媒体类型 / 状态码 / 路径各自干净,OpenAPI 自描述,前端 fetch 分明。**采纳。**(本决策偏离 docs 行 130 草案,apply 阶段回写 architecture.md。)

### D7 — 修 `litellm_image` 照搬 text adapter 范式

**选:** `litellm_image.py` 改造:构造时 `self._base_url = normalize_base_url(snapshot.base_url)`;`generate()` 在 `_base_url` 存在时补 `api_base` + `custom_llm_provider="openai"`;补异常映射(`AuthenticationError`/401/403 → `ProviderAuthFailed` 不重试;`RateLimitError`/`Timeout`/`APIConnectionError`/429/5xx → 1+3 次指数退避重试,耗尽抛 `RateLimited`;其余 4xx 上浮);`probe()` 同步用 `_base_url`。清账 `litellm_image.py:6-8` TODO。

**为什么选 X 不选 Y:**
- *替代 a(新写 image 适配,不经 litellm 直调供应商 httpx)*:违反「模型访问只经 `core/llm` 单一接缝」(NFR-1 供应商无关),且要自维护多供应商差异。否。
- *替代 b(只补 provider/normalize_base_url,不补重试/异常映射)*:限流/超时直接任务 failed,体验差(瞬态错误不可恢复);与 text adapter 不对称。否。
- 照搬 text:已验证(5.5 spike + M2 生产跑通 DeepSeek-V3.2)、对称、最小改动。**采纳。**

### D8 — 门禁:active image 配置 **且** 角色已填 `appearance_desc`

**选:** `generate_portrait` 前置两道门:`require_active_image(user_id)`(无 active+`status='active'` 的 image 配置 → `ModelNotConfigured` 409)+ 角色已填 `appearance_desc`(空 → `InvalidState` 409,details `reason=appearance_required`);前端据 `/api/me` 的 image 配置完成度信号 + 角色 `appearance_desc` 禁用「AI 生成」按钮并提示。

**为什么选 X 不选 Y:**
- *替代 a(仅门禁 BYOK,appearance 可缺)*:无形象描述 → 生成的图与角色无关(随机人脸),用户必重生成,浪费供应商配额。否。
- *替代 b(不门禁,appearance 缺时用角色名兜底 prompt)*:角色名信息量太低,产出不可控;且「必须填写角色相关字段」是用户的明确要求。否。
- 双门禁:符合用户原话「ai生成必须填写角色相关字段」,产出可预期。**采纳。**(prompt 模板:appearance_desc 为主 + name/role_type/persona 辅助,落 `services/character_media_service.py`,**不进 `analysis/`/`graphs/`/`tasks/`**,守 NFR-2。)

### D9 — `selected` 单选简化:旧形象图保留不删

**选:** 每次 generate/upload 产新 `media(selected=true)`,同 `(user_id, owner_type='character', owner_id)` 下旧 media 翻 `selected=false`;`character.image_media_id` 指当前;**旧 media 行与磁盘文件保留**(本期不删、不暴露历史 UI)。

**为什么选 X 不选 Y:**
- *替代 a(覆盖:删旧 media + 删旧文件)*:用户改主意无法回退;删文件有竞态(签名 URL 未过期)。否。
- *替代 b(多候选 picker:存 N 张待选)*:本期 UI 不含 picker(用户未要求),over-engineering。否。
- 单选 + 保留:实现简单、可回退(未来加 picker 零迁移)、磁盘成本可控(单角色几张图)。**采纳。**(磁盘清理策略 Non-Goal,留 M4+。)

### D10 — 签名 URL = HS256(复用 `jwt_secret`),短 TTL,内容端点免 Authorization

**选:** `sign_url` 产 token = HS256 签名的 payload `{sub: media_id, exp: now+300s}`,用现有 `jwt_secret`(`core/config.py:45`,**不引新密钥**);`GET /api/media/:media_id/content?token=&exp=` 验签 + 校 `sub==path.id` + 未过期 → 流式字节(`FileResponse`/`StreamingResponse` + 正确 `content-type`);**不要求 Authorization header**(`<img src>` 直用)。

**为什么选 X 不选 Y:**
- *替代 a(每次 `GET .../image` 内联返回 base64)*:base64 膨胀 ~33%,占响应体且无法被浏览器图片缓存复用。否。
- *替代 b(服务端代理 `GET .../content` 走 Bearer)*:`<img>` 不能带 header(见 D2 替代 a)。否。
- HS256 + jwt_secret 复用:零新密钥管理、与现有令牌同安全基线、`<img src>` 零额外请求头;TTL 5 分钟够页面渲染,过期前端从 `GET .../image` 重取新 token。**采纳。**

## Risks / Trade-offs

- **[远程图下载失败 / URL 过期]** → generate work 闭包内 `httpx.get(远程URL)` 设超时(30s)+ 重试(2 次);失败 → 任务 `failed`(error.code=`rate_limited` 或 `internal_error`),前端可重试。供应商返回 URL 形态多样(litellm `aimage` 返回 `.data[0].url`)→ 严格取该字段,缺失 → `AnalysisParseError` 同款兜底(任务 failed)。
- **[签名 URL 泄露(5 分钟窗口)]** → token 绑定 `media_id`(`sub`),内容端点校 `sub==path.id`,即便泄露也只能取该一张图;TTL 短;`media.user_id` 已是归属隔离(他人 404)。生产可经 nginx / 反代进一步收敛。
- **[Pillow 依赖体积 / 安全]** → Pillow 是图像处理事实标准、纯 Python wheel(无系统依赖);限定接受 `image/{jpeg,png,webp}`,其它 `content_type` → `InvalidState` 422(防 SVG/可执行)。`pip-audit` 随 CI。
- **[磁盘增长无界(D9 保留旧图)]** → 本期单租户/小规模可接受;记录 Non-Goal,留 M4+ 定期清理(`media` 行删 + `FileStore.delete`)。监控 `media` 表行数。
- **[executor 闭包捕获 file_store 的生命周期]** → `file_store` 经 `app.state` 单例构造(lifespan),与 executor 同生命周期;work 闭包捕获的是同一单例引用,无悬挂。测试注入 `InMemoryFileStore` 替身。
- **[image 供应商返回非图片 / 损坏字节]** → 下载后 `Pillow.Image.open(BytesIO)` 探测;失败 → 任务 failed(非 500 挂起),不落盘损坏文件。
- **[本地磁盘 `media_root` 权限/路径]** → 启动时 `Path(media_root).mkdir(parents=True, exist_ok=True)`(lifespan);生产挂载持久卷;`DS_MEDIA_ROOT` env 可覆盖。

## Migration Plan

**部署:**
1. 加依赖:`uv add Pillow httpx`(经清华镜像 `UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`);`uv sync`。
2. 跑迁移:`uv run --directory backend alembic upgrade head`(链 `…→c4a1f9e20b7d→<新>`,建 `media` 表 + `episode_characters.image_media_id` 列)。
3. 配 `DS_MEDIA_ROOT`(默认 `./media`,生产挂卷);`jwt_secret`/`mek` 已有,无需新密钥。
4. 重启后端;前端 `yarn build` 部署。

**回滚:**
- 迁移可逆:`downgrade` 先 `drop_column image_media_id` 再 `drop_table media`(本变更提供 `downgrade` 实现)。
- 代码回滚:`git revert` 本变更提交即可;既有 M2 功能不依赖 `media` 表(分析/分镜路径不触达)。
- **数据保留**:`media` 表为本期新增,删表无既有数据损失;已上传形象图随表删除(可接受,本期切片)。

## Open Questions

- **签名 URL 是否需绑定 `user_id`?** 当前 token 仅绑 `media_id`(`sub`),未带 `user_id`。鉴于 `media_id` 不可枚举(BIGINT)、TTL 5 分钟、内容仅为该角色形象图(非敏感),可不绑 user。apply 阶段若安全评审要求,加 `uid` claim 并在端点比对——低成本。**默认不绑,记录待评审。**
- **`/api/me` 是否补 image 配置完成度信号?** 前端门禁需知「用户是否配了 active image」。`has_active_image` 仓储方法易补,`/api/me` 加一个布尔字段。**倾向补**(前端门禁必需),apply 时确认 schema。
- **upload 硬上限(防滥用)**:Pillow 压缩保证落盘 ≤1MB,但请求体本身需上限防 DoS。倾向 `DS_MEDIA_UPLOAD_MAX_BYTES`(默认 10MB)→ 超限 413。apply 时定阈值与是否新建 domain error。
