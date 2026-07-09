# Tasks

> 实施依据:[proposal](proposal.md) · [design](design.md) · [specs/analysis/spec.md](specs/analysis/spec.md) · 技术方案 [`docs/tech-solution/`](../../../docs/tech-solution/)。
> **仓库为 monorepo**:后端在 `backend/`(Python 包 `drama_smith`,src layout),前端在 `frontend/`;承接 M0(`setup-user-foundation`)、M1(`setup-byok-config`)地基,复用其 ORM/事务/错误/隔离范式(见 M1 D10/M0 D6·D12·D14、[`backend.md §4/§10`](../../../docs/tech-solution/backend.md)、[`database.md §5`](../../../docs/tech-solution/database.md))。
> 顺序按依赖排列;每组末尾「验证」项为该组完成判据;决策理由见 design D1–D13 与「实现注记」(模式/prompt/strategy),不在此重复。

## 1. 依赖与配置

- [x] 1.1 `backend/pyproject.toml` 新增 `langgraph`;`uv sync` 装妥并锁版本
- [x] 1.2 `core/config.py`:`Settings` 增 `max_tasks_per_user`(默认 4)、`max_global_workers`(默认 8),均经 `DS_` 前缀 env 可覆盖;敏感项不动
- [x] 1.3 `.env.example` 补两个并发上限项 + 说明(默认值与 BYOK 成本保护的取值建议,承接 [`总纲 §6`](../../../docs/README.md))
- [x] 1.4 验证:`uv sync` 干净;`get_settings()` 返回两个新字段且默认值正确

## 2. 剧目/角色/分析/任务域表与迁移

- [x] 2.1 `db/models/dramas.py`、`episodes.py`:字段对齐 [`database.md §3.4`](../../../docs/tech-solution/database.md)(`dramas.user_id/sort_order/deleted_at`;`episodes.drama_id/title/sort_order/aspect_ratio(ENUM)/style_preset/status(ENUM)/deleted_at` + `current_analysis_id`(nullable,**逻辑指针不加物理 FK**,D11));遵守 M0 ORM 约定(BIGINT UNSIGNED PK、utf8mb4、`DATETIME(3)` naive-UTC、naming_convention)
- [x] 2.2 `db/models/scripts.py`、`script_versions.py`:`scripts.episode_id` UNIQUE(1:1)+ `current_version_id`;`script_versions` 不可变追加(`version_no`/`content` MEDIUMTEXT/`format` ENUM/`source` ENUM),对齐 [`database.md §3.4`](../../../docs/tech-solution/database.md)
- [x] 2.3 `db/models/episode_characters.py`:对齐 [`database.md §3.5`](../../../docs/tech-solution/database.md);**本期不落 `image_media_id`**(随 M3 `media`),`source` ENUM 取 `'preset','analysis'`(`'library'` 值随 M4);含 `traits` JSON、`sort_order`
- [x] 2.4 `db/models/analyses.py`、`shots.py`、`shot_characters.py`:`analyses.result/config_snapshot/status` + `script_version_id`(FK→script_versions,D11);`shots` 全字段(`seq`/`shot_type` ENUM/`target_duration DECIMAL(5,2)`/`dialogue` 等)+ `(episode_id,seq)` 索引;`shot_characters` 复合 PK,对齐 [`database.md §3.6`](../../../docs/tech-solution/database.md)
- [x] 2.5 `db/models/tasks.py`:全量对齐 [`database.md §3.8`](../../../docs/tech-solution/database.md)(`type/status/progress/stage/trigger/input_snapshot/output_refs/error` JSON + 时间线);`(user_id,status,created_at)` 索引、`episode_id` 索引
- [x] 2.6 `db/models/__init__.py` re-export 全部新模型(Alembic autogenerate 必需,承接 M0 D13)
- [x] 2.7 迁移 `<rev>_add_analysis_core.py`(autogenerate 产出后校准:枚举值集、外键 `ON DELETE`、`(episode_id,seq)` 与任务索引、`analyses.script_version_id` FK、`episodes.current_analysis_id` 逻辑指针**不加物理 FK**避免循环,D11);downgrade 复用 M0/M1 经验(drop_table 前删冗余 drop_index,避免 1553)
- [x] 2.8 验证:`alembic upgrade head` 建 9 张表成功;`downgrade -1` → `upgrade head` 往返通过(env 配置的外部 MySQL)

## 3. 仓储层(归属链 + 强制 user_id 过滤)

- [x] 3.1 `db/repositories/drama_repo.py`:`list/get/create/rename/soft_delete`,签名带 `user_id`;列表带 `deleted_at IS NULL`
- [x] 3.2 `db/repositories/episode_repo.py`:`get(user_id, episode_id)` 经 `JOIN dramas WHERE dramas.user_id` 校验归属链(D1);`list_by_drama/create/update/soft_delete`;`episode_id→user_id` 归属解析供子资源仓储复用
- [x] 3.3 `db/repositories/script_repo.py`:1:1 get/upsert 产版本(`source='input'`)、`set_current_version`、`list_versions`、`get_version`;所有方法先验 episode 归属
- [x] 3.4 `db/repositories/episode_character_repo.py`:CRUD + `bulk_create`(拆解产角色写入)、按 episode 列表;`bulk_create` **返回插入行的 id 列表**(供 service 建 name→id 映射,D13);`source` 写入
- [x] 3.5 `db/repositories/analysis_repo.py`:`create(pending, script_version_id)`(D11)/`update_result`/`get_current(user_id, episode_id)`/`set_current`/`list_history`/`has_inflight(user_id, episode_id)`(查 `pending`/`running` 的 analyze,D3 串行约束)
- [x] 3.6 `db/repositories/shot_repo.py`:`list_by_episode`(按 `seq`)/`bulk_create`/`patch`/`split`/`merge`,拆合排序在事务内 dense-rank 重排 `seq`(D5);`reorder`
- [x] 3.7 `db/repositories/task_repo.py`:`create`/`set_status`/`update_progress`/`finish(succeeded/failed/error)`/`get(user_id, id)`/`interrupt_running`(启动恢复);强制 `user_id` 过滤
- [x] 3.8 验证:仓储单测(复用 `tests/conftest.py` session 夹具)覆盖归属链、软删排除、`has_inflight`、shot 拆合 seq 重排无空洞;两用户数据断言跨用户隔离(`NotFound`)

## 4. `core/llm` 文本 chat() 实现(首次真实调用)

- [x] 4.1 确认 `llm/litellm_text.py` 的 `chat(messages, **params) -> str`(M1 已实现)能经 `**params` 透传 `response_format`/tool-calling;**接缝保持返回 `str`,不引入结构化返回类型**(结构化解析归 `analysis/`,D2)
- [x] 4.2 `llm/base.py`:确认 `TextModel.chat` Protocol 保持 `-> str`(现状);**不在接缝层引入结构化输出契约**(分层对称:接缝不懂 analysis、analysis 不懂 provider;pydantic 模型与解析见 5.2)
- [x] 4.3 有限重试 + 指数退避:仅对 `RateLimited`(429/超时)重试(复用 M1 `_probe_with_retry` 同款,有界次数);401/403/鉴权失败→抛 `ProviderAuthFailed`(不重试)
- [x] 4.4 `tests/llm/fakes.py` 增 `FakeTextModel.chat`(确定性结构化输出、可控成败),承接 [`backend.md §11`](../../../docs/tech-solution/backend.md)
- [x] 4.5 验证:`core/llm` 不 import 任何 `graphs`/`analysis`/`services`/`crypto`(分层自检 grep);`tests/llm/test_llm.py` 覆盖 chat 正常/重试/鉴权失败映射

## 5. 分析图节点 + 提示工程 + 结构化模型(`analysis/`)

- [x] 5.1 `analysis/state.py`:`AnalysisState(TypedDict)`(script/preset_characters/characters/plotlines/conflicts/pacing/shots/aspect_ratio/style_preset),对齐 [`backend.md §5`](../../../docs/tech-solution/backend.md);**`preset_characters` 带 `episode_character_id`、`characters`(extracted)与 `shots[*].appearing` 仅以 name 引用**(落库时解析 id,D13)
- [x] 5.2 `analysis/models.py`:四维 + 分镜的 pydantic 输出模型(`CharacterExtract`/`Plotline`/`Conflict`/`Pacing`/`ShotDraft` 含 3–15s `target_duration`),供 `chat()` 结构化约束(D2/D9);**亦作 `PromptStrategy.output_model`(实现注记)**
- [x] 5.3 `analysis/prompts.py`:**`PromptStrategy` 策略对象集合**(实现注记)——每项能力一个策略(`build_messages`/`output_model`/`response_format(provider)`/`parse`):角色抽取 / 情节线 / 冲突节奏 / 切分镜(含分镜 3–15s 时长约束、按剧情节拍切分、与预置角色融合提示)+ `optimize` 的 copy-edit 策略(明示仅润色、不重写/重排/结构调整,D12);provider 适配与退化(JSON/tool/提示词 JSON+重试)、解析失败映射 `analysis_parse_error` 均在策略层;对齐 [`analysis §5.1`](../../../docs/requirements/features/analysis.md)
- [x] 5.4 `analysis/nodes/`:`extract_characters`、`analyze_plot`、`analyze_conflict`、`analyze_pacing`、`split_shots`;节点仅消费注入的 `TextModel`、**编排各自 `PromptStrategy`(build_messages→chat→parse,节点不掺提示/解析细节,实现注记)**,读/写 `AnalysisState`;**`split_shots` 的 appearing 角色用 name 引用(从 preset+extracted 已知角色清单选)、不输出 db id**(D13)
- [x] 5.5 **结构化输出可靠性 spike**(D2 风险):✅ 已完成 —— DeepSeek-V3.2@SiliconFlow,`extract_characters` ×8:**8/8 纯 JSON、0 解析失败、0 带 fence**(延迟均值 12s)→ **JSON 模式可靠,维持轻量 `JsonPromptStrategy`**(`_extract_json` 留作廉价保险,无需重试铠甲)。spike 另暴露并修复接缝缺陷:给 `base_url` 的自定义 OpenAI 兼容端点缺 `custom_llm_provider="openai"`、且 base_url 未规整(用户填 `…/v1/chat/completions`)→ 真实模型打不通(`litellm_text` 修);连修 probe 假阳(打到 `/chat/completions/models`)与 `test_config` 成功不复位 `status`。原计划:在铺开五节点前,先用 `extract_characters` 单节点 + 角色抽取提示端到端打**用户真实的 active 文本模型**(如 GLM),验证 `response_format` JSON 模式可靠性;据结果定 `analysis/` 的重试/解析铠甲(可靠→轻量;不稳→解析重试 + 失败映射 `analysis_parse_error`)
- [x] 5.6 验证:节点单测用 `FakeTextModel`(确定性输出)覆盖各节点输入→输出、结构化解析失败 → 明确异常;prompts 不含明文 Key

## 6. LangGraph 分析图编排(`graphs/analysis_graph.py`)

- [x] 6.1 `graphs/analysis_graph.py`:建图 `START → extract_characters → fan-out(analyze_plot | analyze_conflict | analyze_pacing) → split_shots → END`(D2);节点经 LangGraph 并行 fan-out
- [x] 6.2 构造入口:`build_analysis_graph(text_model) -> CompiledGraph`;状态流转与节点接线
- [x] 6.3 流式进度归一:节点事件 → `(progress, stage)` 回调(D2,供执行器 progress 写记录);本期可用 `astream_events` 或节点进入/退出钩子
- [x] 6.4 验证:用 `FakeTextModel` 端到端跑通图(输入剧本 → 产出四维 + 分镜);`graphs/` 不 import litellm(分层自检 grep)

## 7. 进程内任务执行器(`tasks/`)

- [x] 7.1 `tasks/states.py`:状态机枚举 + 合法流转表(`pending→running→{succeeded|failed|canceled|interrupted}`),承接 [`backend.md §7.2`](../../../docs/tech-solution/backend.md)
- [x] 7.2 `tasks/executor.py`:`TaskExecutor`(不接 `FileStore`,D4);`submit(task, work)` 落 `pending`→`create_task(_run)`;`_run` 内每用户 `Semaphore(max_tasks_per_user)` + 全局 `Semaphore(max_global_workers)` acquire(超限自然排队 `pending`)→置 `running`→执行 `work(progress_cb)`→`finish`(succeeded/failed/canceled)
- [x] 7.3 `tasks/progress.py`:`progress_cb(task_id)` → `task_repo.update_progress(progress, stage)`(写记录,REST 可读)
- [x] 7.4 `tasks/recover.py`:`interrupt_running()` —— `UPDATE tasks SET status='interrupted', error={code:'restart_interrupted'} WHERE status='running'`(D4,对齐 [`architecture §4.4`](../../../docs/tech-solution/architecture.md))
- [x] 7.5 `TaskExecutor.shutdown()`:取消在跑协程、落 `interrupted`(优雅停止)
- [x] 7.6 验证:`tests/unit/test_executor.py`(假 work + 假 LLM)覆盖状态机、排队、并发上限、cancel→canceled、`interrupt_running`;executor 不耦合业务(只调度)

## 8. service 层(用例编排 + 门禁 + 事务边界)

- [x] 8.1 `services/drama_service.py`、`episode_service.py`:CRUD 用例,事务边界在 service(承接 M0 D14);归属校验经对应 repo
- [x] 8.2 `services/script_service.py`:`upsert_script`(产 `source='input'` 版本,D6)、`optimize_script`(发起异步任务)、`accept_version`/`reject`(移/不移 `current_version_id`)、`list_versions`/`revert`
- [x] 8.3 `services/shot_service.py`:`patch`/`split`/`merge`/`reorder`(事务内 dense-rank 重排,D5);`target_duration` 越界标注(不阻断)
- [x] 8.4 `services/analysis_service.py`:`analyze(user_id, episode_id)`——`require_active_text`(M1 预留)取配置→`crypto.decrypt`→`factory.build`→构造图→`executor.submit(type='analyze', work=run_graph)`;`has_inflight` 串行约束(D3/D8);succeeded 时**新建 analysis(记 `script_version_id`=当时 current 版本,D11)** + 写 `result` + 批量插 `shots`/`shot_characters` + 移 `episodes.current_analysis_id`(旧 analysis 保留可切回)+ 拆解产角色落 `episode_characters`(source='analysis',D7,**不做自动合并**);**落库事务:先 bulk_create extracted 拿 id → 建 name→id 映射(preset 优先)→ 解析 shots.appearing 写 shot_characters,name 归一化失败则跳过 + warning(D13)**;`get_analysis` 返回 `{current_analysis, inflight_task?, stale_flag}`(双语义,D11);`select_current_analysis`(切换 current 指针)
- [x] 8.5 `analyze` 的 `work` 闭包:拉起图、节点调 `TextModel.chat`、进度回调、异常映射(401/403→`set_status(invalid)`+`ProviderAuthFailed`→任务 failed,D8);`input_snapshot` 含剧本版本 + 模型配置快照(D9)
- [x] 8.6 `optimize` 的 `work` 闭包:取当前剧本→`TextModel.chat`(**copy-edit 提示**:格式/错别字/标点/对白润色,**明示不做重写/重排/结构调整**,D12)→产 `source='optimize'` 新版本 + **后端 `difflib` 段落级 diff**(`[{seg,before,after,change_type}]`,段落切分 plain 按空行/markdown 按段落·标题/fountain 按场景头,`script_service` 小函数、不引 fountain parser;经 `output_refs` 返回、**不落库**)→任务 succeeded 返回新版本 id + diff;**采纳整版**(accept/reject,D12,前端只读 view)
- [x] 8.7 验证:service 单测(Fake LLM 替身)覆盖 analyze/optimize 正常 + 门禁(`ModelNotConfigured`)+ 串行约束(`invalid_state`)+ 鉴权失败置 invalid + 越界标注;事务边界正确(repo 只 flush,service commit)

## 9. 错误码、依赖接线与路由挂载

- [x] 9.1 `core/errors.py`:确认 `ModelNotConfigured`/`ProviderAuthFailed`/`RateLimited`/`InvalidState`(M1 已登记 `invalid_state`/`model_not_configured` 等);新增 `analysis_parse_error`(结构化解析失败,500 或 422 映射,对齐 D2 风险缓解)经 `_domain_error_handler` 登记
- [x] 9.2 `api/deps.py`:增 `get_executor()` 依赖(读 `app.state.executor`);复用 `get_crypto`/`get_current_user`
- [x] 9.3 `main.py`:lifespan 内构造 `TaskExecutor(engine, max_per_user, max_global_workers)` + `await executor.recover_running()`;`app.state.executor` 注入;yield 后 `await executor.shutdown()`;挂载新路由(`/api/dramas`…、`/api/tasks`)与 Swagger tag;CORS 不变
- [x] 9.4 验证:`create_app()` 起 app;lifespan 启动期 `recover_running()` 空跑无副作用;`/openapi.json` 含新端点与新错误码

## 10. 剧目/剧本/角色/分析/分镜/任务 API(`api/`)

- [x] 10.1 `api/schemas.py`:扩展剧目/剧集/剧本/角色/分析/分镜/任务的请求与响应模型(Public 模型不含敏感项);`ScriptOptimize` 任务返回 `task_id` + succeeded 后的 `version_id`/diff
- [x] 10.2 `api/dramas.py`:`POST/GET /api/dramas`、`POST/GET /api/dramas/:dramaId/episodes`、`GET/PUT/DELETE /api/episodes/:id`(均 Bearer + 强制隔离,契约 [`architecture §3.3 ④`](../../../docs/tech-solution/architecture.md))
- [x] 10.3 `api/episodes.py`(剧本):`PUT /api/episodes/:id/script`(写/产版本)、`POST /api/episodes/:id/script/optimize`(异步任务,202 返回 task_id)
- [x] 10.4 `api/characters.py`:`GET/POST/PUT/DELETE /api/episodes/:id/characters[/:cid]`(预置角色 CRUD;`fromLibraryId` 引入本期不实现,M4)
- [x] 10.5 `api/analysis.py`:`POST /api/episodes/:id/analyze`(异步,202;门禁→409/422;串行→409)、`GET /api/episodes/:id/analysis`(返回 `{current_analysis, inflight_task?, stale_flag}`,D11 双语义;无合并建议)、`PATCH /api/episodes/:id/analysis/current`(切换 current_analysis_id 到指定历史 analysis,D11)
- [x] 10.6 `api/shots.py`:`GET /api/episodes/:id/shots`(返回 current_analysis 名下的分镜,D11)、`PATCH /api/shots/:id`、`POST /api/shots/:id/split`、`POST /api/shots/:id/merge`(作用于 current analysis 的 shots;越界标注不阻断)
- [x] 10.7 `api/tasks.py`:`GET /api/tasks/:id`(单任务轮询,REST 基线)+ `POST /api/tasks/:id/cancel`(协作式取消 running,已落地产物保留→canceled,D4);**`GET /api/tasks` 聚合列表、retry 本期不实现(M5)**
- [x] 10.8 验证:`tests/test_analysis_api.py`(HTTP 流测试置于 `tests/` 根,与 `test_models_api.py` 同范式)覆盖 dramas/episodes/script/characters/analyze/shots/tasks 正常 + 异常(409 门禁/串行、422 无剧本、跨用户 404)+ 拆解端到端(Fake LLM)轮询 pending→running→succeeded→取 analysis/shots;cancel running→canceled→同剧集可重发 analyze

## 11. 后端测试与质量门

- [x] 11.1 集成测试:`tests/test_analysis_api.py` 全流水线(建剧→建剧集→写剧本→optimize 轮询→预置角色→analyze 轮询→取 analysis/shots→编辑分镜 拆/合/排序)+ 错误路径
- [ ] 11.2 隔离测试:两用户数据,断言跨用户访问 drama/episode/script/character/shot/analysis/task 一律 404
- [ ] 11.3 任务记录测试:并发上限排队(pending)、`interrupt_running`(模拟 running→重启→interrupted)、`input_snapshot` 含模型快照、`GET /api/tasks/:id` 跨重载可读
- [ ] 11.4 结构化解析失败路径:Fake LLM 返回非法 JSON → 任务 failed(`analysis_parse_error`),不 500 挂起
- [ ] 11.5 质量门:`ruff check`、`mypy src/drama_smith tests`、`pytest --cov`(核心模块 `graphs`/`analysis`/`tasks`/新 service 覆盖率达标,整体 ≥ M1 基线)

## 12. 前端类型与 API 客户端

- [x] 12.1 `frontend/src/types/`:`Drama`/`Episode`/`AspectRatio`/`EpisodeStatus`/`Script`/`ScriptVersion`/`ScriptFormat`/`EpisodeCharacter`/`AnalysisResult`(四维)/`AnalysisSummary`(`{current_analysis, inflight_task?, stale_flag}`,D11)/`Shot`/`ShotType`/`Task`/`TaskStatus`/`TaskType`;`index.ts` re-export;`tsc` 全绿
- [x] 12.2 `frontend/src/api/endpoints.ts`:新增 `dramasApi`/`episodesApi`(含 script/optimize)/`charactersApi`/`analysisApi`/`shotsApi`/`tasksApi`,复用 M0 `request` 封装(401 自动刷新、204→null);`tsc`+`eslint` 全绿

## 13. 前端剧库 + 剧集工作台 + 分镜编辑台

- [x] 13.1 `routes/DramasPage.tsx`(实现版替换占位):剧列表 → 进剧看剧集列表;新建剧/剧集(建剧集时设画幅/风格);剧/剧集重命名/删除(软删);Zustand store + 手动 `request`(D10,不引 TanStack Query)
- [x] 13.2 剧集工作台(`features/episode/`):剧本输入(粘贴,format 选择)+ 版本切换/回退;可选「AI 优化」发起 → 轮询 `GET /api/tasks/:id`(指数退避 2–5s,D10)→ 比对预览(**只读 diff view**,后端已算段落 diff、前端不计算)→ 整版接受/拒绝(无段落级部分采纳,D12);角色预置 CRUD;「发起拆解」按钮(文本未配→禁用并引导设置)
- [x] 13.3 拆解轮询 + 结果:发起后轮询任务进度(stage/progress);succeeded 后拉 `GET /analysis`(`{current_analysis, inflight_task?, stale_flag}`,D11)+ `GET /shots`;`stale_flag` 为真时标「⚠️ 基于旧版剧本,建议重新拆解」(不阻断)+ 提供「切回历史分镜」入口(调 `PATCH /analysis/current`);角色按 `source`(preset/analysis)分组展示、手动 CRUD 去重(D7,无自动合并 UI);任务卡住可点「取消」(调 `POST /api/tasks/:id/cancel`)后重发
- [x] 13.4 分镜编辑台(`features/shots/`):分镜清单(按 seq)、逐镜编辑(描述/景别/时长/出场角色/对白)、拆/合/排序;`target_duration` 越界高亮提示(不阻断,D5)
- [x] 13.5 `LibraryPage`/`TasksPage` 维持占位(M4/M5);路由与 AppShell 导航更新
- [x] 13.6 验证:`tsc` + `eslint` + `vite build` 全绿;端到端人工跑通(登录→建剧/剧集→写剧本→optimize→预置角色→analyze 轮询→取结果→编辑分镜)待用户在后端在跑时验收

## 14. 联调与收尾

- [ ] 14.1 前后端本地联调通路:均连 env 外部 MySQL;后端 `uv run uvicorn drama_smith.main:app --reload`、前端 `yarn dev`;`langgraph` 依赖与 `DS_MAX_TASKS_PER_USER`/`DS_MAX_GLOBAL_WORKERS` 注记入 README 启动段与依赖表
- [ ] 14.2 文档同步:若实施中偏离源文档(如 `analyses.result` 结构、`tasks` 字段、`episode_characters` 暂缺 `image_media_id`),在收尾时回写 [`docs/tech-solution/`](../../../docs/tech-solution/) 对应章节(database.md §3.5/§3.6、backend.md §5/§7)
- [ ] 14.3 `openspec status --change setup-structured-analysis`:proposal / specs(analysis)/ design / tasks 工件齐备且 `openspec validate` 通过;实施完成,待 `/opsx:archive`
