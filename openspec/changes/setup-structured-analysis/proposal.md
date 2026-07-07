## Why

M1(`setup-byok-config`)已让用户能安全配置、切换、自检文本模型凭证,并接通 `/api/me` 的 `text_model_configured` 完成度门禁。但截至目前,drama-smith 仍是「空地基」——用户登录后没有可用的创作对象:**剧 / 剧集容器、剧本输入、文本结构化拆解、可编辑分镜**全部缺失**,**`core/llm` 文本接缝也从未被真实调用过**(M1 仅自检路径触达)。本变更为里程碑 **M2**,落地流水线的「分析核心」:把已有剧本走通「**剧/剧集 → 剧本输入(可选 AI 优化)→ 预置角色 → 文本拆解 → 可编辑分镜**」,并首次以 LangGraph 分析图经 `core/llm` 真实调用文本模型;同时为支撑拆解这类「耗时不确定」步骤,引入**任务记录雏形**(进程内 asyncio 执行器 + `tasks` 表 + REST 轮询),使「关页面回来继续看」成立。承接 M0/M1 地基,为 M3(视觉素材/视频)提供结构化输入。

## What Changes

- **新增剧目域表**(`backend/src/drama_smith/db/models/`):`dramas`、`episodes`(含画幅 `aspect_ratio` / 风格 `style_preset` / 工作台 `status`)、`scripts`(每剧集 1:1)+ `script_versions`(版本/比对/回退,字段对齐 [`database.md §3.4`](../../../docs/tech-solution/database.md))。
- **新增剧集角色域表**:`episode_characters`(富字段角色:`name`/`role_type`/`persona`/`motivation`/`traits`/`appearance_desc`/`source`/`sort_order`,对齐 [`database.md §3.5`](../../../docs/tech-solution/database.md));**本期不落 `image_media_id`**(形象参考属 FR-A7,随 M3 `media` 表一起加列)。
- **新增分析产物域表**:`analyses`(完整四维结果 `result` JSON + `config_snapshot` + `status`)、`shots`(可编辑分镜:`seq`/`description`/`shot_type`/`scene`/`dialogue`/`target_duration` 等)、`shot_characters`(单镜出场角色多对多),对齐 [`database.md §3.6`](../../../docs/tech-solution/database.md)。
- **analysis 版本化与剧本同构(D11)**:`analyses.script_version_id`(记录「基于哪版剧本」)+ `episodes.current_analysis_id`(当前生效分析指针);重分析新建 analysis 并移指针、旧 analysis 保留可切回(用户手编不丢),剧本变更后对陈旧 analysis 标记提示而不作废;`GET /analysis` 双语义返回 `{current_analysis, inflight_task?, stale_flag}`。
- **新增任务域表**:`tasks`(`type`/`status`/`progress`/`stage`/`input_snapshot`/`output_refs`/`error`/时间线,全量对齐 [`database.md §3.8`](../../../docs/tech-solution/database.md)),作为 M2「任务记录雏形」与 M5 任务中心的共同底座。
- **新增 LangGraph 分析图**(`graphs/analysis_graph.py`)+ `analysis/`(`state.py` TypedDict、`nodes/` 抽取角色 / 情节线 / 冲突节奏 / 切分镜、`prompts.py` 提示工程含分镜 3–15s 时长约束与预置角色融合),对齐 [`backend.md §5`](../../../docs/tech-solution/backend.md)。图为 `START → extract_characters → (analyze_plot | analyze_conflict | analyze_pacing) → split_shots → END`;节点**仅**消费 `core/llm` 构造的 `TextModel`,绝不直耦合 litellm/厂商 SDK(NFR-2)。
- **首次真实调用 `core/llm` 文本接缝**:`llm/litellm_text.py` 增 `chat()` 实现(M1 仅留 Protocol + `probe()`);解密 Key 仅驻内存;供应商 401/403 → 置 `model_configs.status=invalid` + 抛 `ProviderAuthFailed`、429/超时 → 有限重试(M1 已定义错误码,M2 首次在分析路径触发)。
- **新增进程内任务执行器**(`tasks/`):`executor.py`(asyncio + 每用户 `Semaphore` + 全局协程上限 + 排队)、`states.py`(状态机枚举与流转)、`recover.py`(启动扫描 `running → interrupted`)、`progress.py`(进度回调 → 更新 `tasks` 记录);承接 [`backend.md §7`](../../../docs/tech-solution/backend.md) 与 [`architecture §4`](../../../docs/tech-solution/architecture.md)。**本期执行器不依赖 `FileStore`**(M2 无富媒体;M3 引入 `media` 时再注入)。
- **新增剧目/剧本/角色/分析/分镜 API**(REST,均 Bearer + 强制 `user_id` 隔离,契约见 [`architecture §3.3 ④⑤⑥`](../../../docs/tech-solution/architecture.md)):`/api/dramas`、`/api/dramas/:dramaId/episodes`、`/api/episodes/:id`、`PUT /api/episodes/:id/script`、`POST /api/episodes/:id/script/optimize`(异步任务,**纯 copy-edit**:格式/错别字/标点/对白润色,产出新版本 + 后端 `difflib` 段落级 diff;节奏/结构归拆解 pacing)、`/api/episodes/:id/characters`、`POST /api/episodes/:id/analyze`(异步任务)、`GET /api/episodes/:id/analysis`、`GET /api/episodes/:id/shots`、`PATCH /api/shots/:id`、`POST /api/shots/:id/split`、`POST /api/shots/:id/merge`。
- **新增任务轮询 + 取消端点(REST 基线)**:`GET /api/tasks/:id`(查单任务进度/状态/错误/产物)作为「关页面回来看」的保证;`POST /api/tasks/:id/cancel`(协作式取消 `running`,已落地产物保留)—— 执行器已内建 cancel 路径,M2 开放此最小端点以解「卡死任务无法重发」(详见 design D4)。**`retry` 端点、跨剧集聚合列表 `GET /api/tasks`、WebSocket `/ws/tasks`、任务中心页仍属 M5**,本期显式 Non-Goal。
- **新增前端剧库 + 剧集工作台**:落地 `DramasPage`(剧/剧集两级 CRUD,替换占位)、剧集工作台(剧本输入 + 版本切换、可选 AI 优化发起 → **只读 diff view 预览 + 整版接受/拒绝**(无段落级部分采纳)、角色预置 CRUD、发起拆解 + 轮询进度)、分镜编辑台(清单展示、逐镜编辑、拆/合/排序、3–15s 校验提示)。**复用 M0/M1 的 Zustand + 手动 `request()` 范式**(不引 TanStack Query);`LibraryPage`/`TasksPage` 维持占位(分属 M4/M5)。
- **新增依赖**:后端 `langgraph`(分析图编排);前端无新增运行时依赖。

## Capabilities

### New Capabilities

- `analysis`: 围绕「剧(Drama)→ 剧集(Episode)」两级容器,把已有剧本走通「**剧本输入(可选 AI 优化)→ 预置角色 → 文本结构化拆解(角色/情节线/冲突/节奏 + 分镜 3-15s)→ 可编辑分镜**」的分析核心;首次经 LangGraph 分析图 + `core/llm` 文本接缝真实调用文本模型;以「任务记录雏形」(进程内执行器 + `tasks` 表 + REST 轮询 `GET /api/tasks/:id`)支撑拆解/优化这类长步骤,使「关页面回来继续看」成立。需求条目对齐 [`docs/requirements/features/analysis.md`](../../../docs/requirements/features/analysis.md) FR-A1~A6(任务记录对应 FR-A11 的雏形切片,含最小 `POST /api/tasks/:id/cancel` 解卡死任务)。**角色「自动合并建议」(名称相似度匹配 + 确认 UX)推迟至 M4 随角色库一起做;M2 拆解产角色仅落库标 `source='analysis'`、与预置角色并列、由用户手动 CRUD 去重。**

### Modified Capabilities

<!-- 无。M0 `user-auth`、M1 `ai-config` 的 spec 级行为本变更不改:
`GET /api/me` 的 `text_model_configured` 已于 M1 接通真实值;M2 仅在分析 service 层复用 M1 预留的 `require_active_text(user_id)`(抛 `ModelNotConfigured`)作为拆解/优化的硬门禁,不改 ai-config 的需求条目。-->

## Impact

- **代码**:
  - 后端新增表模型 `db/models/{dramas,episodes,scripts,script_versions,episode_characters,analyses,shots,shot_characters,tasks}.py` + `db/models/__init__.py` re-export;仓储 `db/repositories/{drama_repo,episode_repo,script_repo,episode_character_repo,analysis_repo,shot_repo,task_repo}.py`(签名一律带 `user_id`,承接 M0 D6)。
  - 新增 `graphs/analysis_graph.py`、`analysis/{state,nodes/,prompts}.py`、`tasks/{executor,states,recover,progress}.py`、`services/{drama_service,episode_service,script_service,analysis_service,shot_service}.py`(事务边界在 service,承接 M0 D14);`api/{dramas,episodes,characters,shots,analysis,tasks}.py` + `api/schemas.py` 扩展;`api/deps.py` 增 `get_executor` 依赖。
  - 修改 `llm/litellm_text.py`(实现 `chat()`)、`main.py`(挂载新路由 + lifespan 内 `executor.recover_running()` + 优雅 `shutdown()`)、`core/config.py`(增 `max_tasks_per_user`/`max_global_workers`)。
  - 前端新增 `routes/DramasPage`(实现版替换占位)、剧集工作台组件树(`features/episode/*`)、分镜编辑台(`features/shots/*`)、`api/endpoints.ts` 的 dramas/episodes/script/characters/analysis/shots/tasks 段、`types/` 对应类型;`stores/` 扩展工作台状态。
- **API**:新增剧目/剧本/角色/分析/分镜域端点(见上,契约 [`architecture §3.3 ④⑤⑥`](../../../docs/tech-solution/architecture.md))+ `GET /api/tasks/:id`(单任务轮询)+ `POST /api/tasks/:id/cancel`(取消 running,§3.3 ⑧ 的 M2 最小切片);发起拆解/优化为异步任务(返回 `task_id`)。
- **数据库**:新增 9 张表(dramas/episodes/scripts/script_versions/episode_characters/analyses/shots/shot_characters/tasks)+ Alembic 迁移;`episode_characters.image_media_id` 与 `media` 表本期不建(随 M3)。复用 M0 的 ORM 约定(BIGINT UNSIGNED PK、utf8mb4、`DATETIME(3)` naive-UTC、naming_convention、软删 `deleted_at`)。
- **依赖**:后端新增 `langgraph`;前端无新增。无新增环境变量(`max_tasks_per_user`/`max_global_workers` 走 `Settings` 默认,可 `.env` 覆盖)。
- **文档**:实施依据为 [`docs/tech-solution/`](../../../docs/tech-solution/) 的 `database.md §3.4/§3.5/§3.6/§3.8`、`backend.md §5/§6/§7/§10`、`architecture.md §3.3 ④⑤⑥⑧(部分)/§4`、`frontend.md` 工作台/分镜段,以及需求 [`docs/requirements/features/analysis.md`](../../../docs/requirements/features/analysis.md) FR-A1~A6;本变更为 M2 切片。**文档同步(apply 阶段)**:源文档已在 M1 收尾同步至最新,本变更若实施中出现偏离(如 `analysis.result` 结构、`tasks` 字段微调),在收尾时一并回写对应章节。
