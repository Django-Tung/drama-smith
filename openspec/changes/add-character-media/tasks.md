# Implementation Tasks — add-character-media

> 依据:`proposal.md`(范围)、`design.md` D1–D10(怎么实施)、`specs/character-media/spec.md`(SHALL/场景)。
> 全程:中文 commit、**不带** `Co-Authored-By` 尾注;后端 `uv run`(python3 被 uv 拦截)、`UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`;前端 `yarn`(非 npm)。`analysis/`/`graphs/`/`tasks/` 包**不得** import litellm/crypto/storage/services(NFR-2)。

## 1. 依赖与配置

- [x] 1.1 后端加依赖:`uv add Pillow httpx python-multipart`(httpx 已在依赖树;`python-multipart` 为 `UploadFile` multipart 所需)。
- [x] 1.2 `core/config.py` 增字段:`media_root: str = "./media"`、`media_signed_url_ttl_seconds: int = 300`、`media_upload_max_bytes: int = 10 * 1024 * 1024`(硬上限;软压缩阈 1 MiB 写死在 service)。
- [x] 1.3 验证:既有全绿(263 passed,覆盖率 92.3%,零回归)。

## 2. 数据库模型与迁移

- [x] 2.1 `db/models/media.py`:`Media` ORM(BIGINT UNSIGNED PK、`user_id` FK、`kind`/`owner_type`/`source`/`status`/`storage_provider` ENUM、`storage_key`、`content_type`、`size_bytes`、`width`/`height`/`duration_sec` NULL、`selected` BOOL、`extra` JSON、`provider_task`、时间戳)。**单选约束改为生成列 `selected_key` + UNIQUE**(镜像 `model_configs.active_key`:MySQL 允许多 NULL,旧图保留不删 D9),非 `UNIQUE(owner_type, owner_id, selected)`;复合索引 `(user_id, owner_type, owner_id)`。
- [x] 2.2 `db/models/episode_characters.py`:加 `image_media_id: Mapped[int | None]`(BIGINT UNSIGNED NULL,逻辑指针无 FK),清 `TODO(M3)`。
- [x] 2.3 `db/models/__init__.py`:re-export `Media`。
- [x] 2.4 Alembic 迁移 `8f2a7c4d1e6b`(`down_revision = "c4a1f9e20b7d"`):`create_table("media")`(含 `selected_key` 生成列 + `uq_media_selected_key` + FK + 索引)+ `add_column episode_characters.image_media_id`;`downgrade` 可逆。
- [x] 2.5 验证:`alembic upgrade head` / `downgrade -1` 往返一致已验证。

## 3. storage 抽象(本地落盘 + 签名 URL)

- [x] 3.1 `storage/base.py`:`FileStore` Protocol —— `save`/`read`/`delete`/`sign(media_id) -> (token, exp)`/`verify(token, media_id) -> bool`(`runtime_checkable`)。命名简为 `sign`/`verify`(非 `sign_url`/`verify_token`)。
- [x] 3.2 `storage/local.py`:`LocalFileStore(media_root, secret, ttl_seconds)` —— `save` 落 `<root>/<user_id>/<yyyy>/<mm>/<uuid>.<ext>`;`sign` HS256 `{sub, exp}` 复用 `jwt_secret`(无新密钥,D10);`verify` 校签名 + `sub==media_id` + 未过期;`build_signed_url(media_id, token, exp) -> "/api/media/<id>/content?token=&exp="`。
- [x] 3.3 验证:`tests/unit/test_storage.py` —— save/read/delete 往返、user_id 路径隔离、sign/verify 真伪(对/错 id、篡改 token、错 secret、过期)、URL 格式。

## 4. 修 image LLM 接缝

- [x] 4.1 `llm/litellm_image.py`:镜像 `litellm_text` 重构 —— 构造期 `normalize_base_url`;`generate` 调 **`litellm.aimage_generation`**(非 `aimage`——litellm 真实异步图生成入口),`_base_url` 给定时补 `api_base`+`custom_llm_provider="openai"`;异常映射(Auth→`ProviderAuthFailed` 不重试;RateLimit/Timeout/429/5xx→1+3 次退避;4xx 上浮);`probe` 用 `_base_url`。
- [x] 4.2 验证:`tests/llm/test_llm.py::TestLitellmImage` —— `monkeypatch litellm.aimage_generation`:返回 url、透传 prompt/model/params、Auth 单次不重试、RateLimit 重试后成/耗尽抛 `RateLimited`、base_url 路由(原生不带)、probe 规整。兼补 `normalize_base_url` 去 `/images/generations`/`/embeddings` 后缀用例。

## 5. image 配置门禁

- [x] 5.1 `model_config_repo.py`:加 `get_active_image_config`(镜像 text)+ `has_active_image`。
- [x] 5.2 `model_config_service.py`:加 `require_active_image`(无 active 且 status=active 的 image 配置 → `ModelNotConfigured`)+ `build_image_model_from_config(config, mek, *, model_factory=None)`(解密→factory→isinstance `ImageModel`)。
- [x] 5.3 验证:经 `test_character_media_api` 门禁用例覆盖(无配置 → 409 model_not_configured);`has_image_configured` 经 `/api/me` `image_model_configured` 覆盖。

## 6. media 仓储

- [x] 6.1 `db/repositories/media_repo.py`:`create`(`selected=True` 时先 sql_update 翻同 owner 旧行 False,避免 `selected_key` UNIQUE 冲突)+ `get`(强制 user_id)+ `get_current_for_owner(*, owner_type, owner_id)`(命名泛化 `owner_type`,非仅 character,为 shot/library 预留)+ `get_by_id`(内容端点用,不按 user 过滤——token 即凭证)。
- [x] 6.2 验证:`tests/unit/test_media_repo.py` —— 新行 selected + 旧行翻 False 仍保留、非 selected 不动当前、per-owner 单选、跨用户 NotFound、get_by_id 忽略 user。

## 7. character_media_service

- [x] 7.1 `services/character_media_service.py`:`get_portrait`(归属校验 + 当前 media;无 → None→端点 204;有 → 签名 URL 视图)。
- [x] 7.2 `upload_portrait(*, file_store, data, max_bytes)` —— 超 max_bytes → `MediaTooLarge`(413);Pillow `_decode_image`(失败/不支持 → **`MediaInvalid`**(422,新增语义化错误,非 `InvalidState`));超 1 MiB `_recompress_jpeg` 递降质量;落盘 + `media_repo.create(source='upload', selected=True)` + `set_image_media` + commit。
- [x] 7.3 `generate_portrait(*, mek, file_store, executor, model_factory=None)` —— 门禁(`require_active_image` + `appearance_desc` 非空白,否 → `InvalidState reason='appearance_required'`)→ 建 `tasks.type='image'` → commit → work 闭包(`file_store`/`mek`/冻结 config 经闭包捕获,D4 executor 签名不变):`build_image_model_from_config`→`generate(prompt)`→`_download_image`(httpx 重试 + **兼 data URI 解码** b64)→`_probe_image`→落盘→`_persist_portrait`(自建 session 写 media + 更新指针 + commit)→返 `{media_id}`;Auth 失败 → `mark_config_invalid`。
- [x] 7.4 验证:经 `test_character_media_api` 覆盖(upload 全链路 + 越权 + 非 image 422 + 超大 413 + 单选替换;generate 成功轮询 + 读取 + 三门禁 + 越权)。

## 8. API 端点与装配

- [x] 8.1 `api/schemas.py`:`MediaPublic`(media_id/signed_url/content_type/width/height/source/created_at);`EpisodeCharacterPublic` 加 `image_media_id`;`UserPublic` 加 `image_model_configured`。
- [x] 8.2 `api/characters.py` 加 image 子路由(命名 `/portrait/*`,REST 子资源更清晰,非 `/image/*`):`POST .../portrait/upload`(`Annotated[UploadFile, File()]`,201)+ `POST .../portrait/generate`(202)+ `GET .../portrait`(无图 204,返 `Response(status=204)`)。错误响应 413/422/409 + `_NOT_FOUND`。
- [x] 8.3 `api/media.py`(新):`GET /api/media/{media_id}/content?token=&exp=`(tags=media)—— `file_store.verify` 失败 → `Unauthenticated`(401);`media_repo.get_by_id`(token 即凭证,不校 user)→ 404;`file_store.read` → `Response(content, media_type, Cache-Control)`。
- [x] 8.4 `api/deps.py` + `main.py`:`FileStoreDep`(从 `app.state.file_store`);lifespan 构造 `LocalFileStore(media_root, jwt_secret, ttl)` + `ensure_root()` 注入 `app.state.file_store`;executor 签名不变;挂 `media_router` + 新 `media` tag。
- [x] 8.5 验证:`tests/test_character_media_api.py`(13 用例:upload/generate/get 三端点 + 内容端点 + 门禁 + 单选 + 越权 + 凭证校验)+ `test_app_lifespan`(file_store 注入断言);全量 263 passed / 覆盖率 92.3%。

## 9. 前端(剧集角色形象图 UI)

- [x] 9.1 `types/drama.ts`:加 `MediaPublic`(media_id/signed_url/content_type/width/height/source/created_at)+ `MediaSource`、`EpisodeCharacter.image_media_id`、`TaskType` 加 `'image'`;`types/auth.ts::User` 加 `image_model_configured`;`types/index.ts` 导出新增。
- [x] 9.2 `api/endpoints.ts`:`charactersApi.getPortrait`/`uploadPortrait`/`generatePortrait`(命名随 `/portrait/*` 路由,与 §8.2 同款「非 /image/*」);`uploadPortrait` 用 `FormData`,`request` 不设 content-type 由浏览器带 boundary、返 `MediaPublic`;`getPortrait` 204 → null;`mediaApi` 不需(签名 URL 直拼 `<img src>`)。
- [x] 9.3 `components/ui/avatar.tsx`(新,轻量自建无 Radix):`<Avatar src|null name size />`,src 用签名 URL,无则取 `name` 首字符圆形占位(兼容中英文)。
- [x] 9.4 `features/episode/CastTab.tsx`:新增 `CharacterCard`(每卡自带 portrait 状态 + `useTaskPolling` image 轮询),`CharacterGroup` 改渲染 `CharacterCard`;头像 `<Avatar>` 挂载 / 操作后 `getPortrait` 拉签名 URL;「上传图片」隐藏 `<input type=file accept=image/*>` → `uploadPortrait` → 刷新;「AI 生成」`generatePortrait` → `useTaskPolling` 终态 succeeded 后 `getPortrait` 刷新;门禁 `image_model_configured` 假 或 `appearance_desc` 空 → 禁用「AI 生成」+ `<Tooltip>` 提示(span 包裹 disabled 按钮以承载 hover)。形象图对 preset / analysis 两源均开放(与文本字段可编辑性解耦)。
- [x] 9.5 验证:`yarn typecheck`(tsc)+ `yarn lint`(eslint)+ `yarn build`(tsc && vite build)全绿(strict TS `noUnusedLocals/Parameters`);无新运行时依赖(`package.json` 未动)。

## 10. 收尾:质量门 + 文档同步 + 提交

- [x] 10.1 后端门:`uv run ruff check .` 全绿(仅 1 处 baseline `analysis_graph.py:41` E501,非本变更文件,不动)+ `uv run pytest --cov --cov-fail-under=90`(已过 92.3%,263 passed)。
- [ ] 10.2 `alembic upgrade head` 外部 MySQL 实跑通过(已至 head `8f2a7c4d1e6b`,`media` 表 + `episode_characters.image_media_id` 已建);**前后端联调待用户验收**:后端 `uv run uvicorn drama_smith.main:app --reload` + 前端 `yarn dev`:登录 → 建剧/剧集 → 预置角色填 appearance_desc → 配 image 模型 → 角色卡上传图片(渲染)+ AI 生成(轮询→渲染)+ 越权 404 + 无门禁禁用。
- [x] 10.3 文档回写(apply 阶段发现的偏离):`architecture.md` §⑤ 合一端点改为 get/upload/generate 三条 `/portrait/*` + 内容端点 `/api/media/:id/content`;`backend.md` lifespan 构造 `LocalFileStore(media_root, jwt_secret, ttl)` + `ensure_root()`、§8 重写 `FileStore` Protocol(sign/verify/build_signed_url)+ 签名 URL/压缩细节、配置补 `media_signed_url_ttl_seconds`/`media_upload_max_bytes`;`database.md` §3.7 `media` 表对齐迁移(含 `selected_key` 生成列 + UNIQUE、`extra`/`provider_task`/`last_tested_at`)+ 唯一约束汇总补 `selected_key`。
- [x] 10.4 `openspec validate add-character-media` 通过(「Change is valid」);**归档待用户验收后** `openspec archive add-character-media`。
- [ ] 10.5 提交:中文 commit、**不带** `Co-Authored-By: Claude` 尾注;直接落 `main`(单人无 PR)。后端(ab5522a 已提)/ 前端 / 文档分批提交。
