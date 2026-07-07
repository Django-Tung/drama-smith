## Context

drama-smith 已在 M0(`setup-user-foundation`)落地多用户地基(FastAPI 分层、MySQL + SQLAlchemy 2.0 async + Alembic、注册/登录/刷新、仓储层「强制 `user_id` 过滤」隔离范式),并在 M1(`setup-byok-config`)落地 BYOK:`model_configs` 表(信封加密 + 每用途唯一 active)、`core/crypto.py`、`core/llm` 接缝(`TextModel`/`ImageModel`/`VideoModel` Protocol、litellm text/image + 视频适配器占位、零成本 `probe()`)、模型配置 API、`GET /api/me` 的 `text_model_configured` 真值门禁,以及 service 层预留但**未被调用**的 `require_active_text(user_id)`。

**当前状态**:后端有 `core/{config,security,crypto,errors}.py`、`db/{base,session,models/{users,refresh_tokens,model_configs},repositories/{user,refresh_token,model_config}_repo}`、`services/{auth,model_config}_service`、`api/{auth,me,models,health,schemas,deps}`、`llm/{base,factory,litellm_text,litellm_image,adapters,_probe}`;**无** `graphs/`、`analysis/`、`tasks/`、`storage/`,无剧目/剧集/剧本/角色/分析/分镜/任务表。前端有 auth/settings/setup 向导,`DramasPage`/`LibraryPage`/`TasksPage` 为占位卡。

**本期(M2)** 在该地基上落地**分析核心**:剧/剧集两级容器 → 剧本输入(可选 AI 优化)→ 预置角色 → 文本结构化拆解(角色/情节线/冲突/节奏 + 分镜 3-15s)→ 可编辑分镜,并**首次真实调用文本模型**(经 LangGraph 分析图 + `core/llm` 文本接缝),同时引入**任务记录雏形**支撑拆解/优化这类长步骤。

**约束(承接)**:多租户强制 `user_id` 隔离与越权 404(M0 D6)、供应商无关单一接缝 NFR-2(`graphs`/`analysis` 绝不直 import litellm/厂商 SDK,见 [`backend.md §1`](../../../docs/tech-solution/backend.md))、任务可恢复 FR-A11(进程内 asyncio 执行器 + 持久化,见 [`architecture §4`](../../../docs/tech-solution/architecture.md))、文本模型强制配置门禁(FR-C1,复用 M1 预留 `require_active_text`)。需求条目见 [`docs/requirements/features/analysis.md`](../../../docs/requirements/features/analysis.md) FR-A1~A6(任务记录为 FR-A11 雏形切片)。

## Goals / Non-Goals

**Goals:**

- 剧目域表(`dramas`/`episodes`/`scripts`/`script_versions`)+ 剧集角色域(`episode_characters`)+ 分析产物域(`analyses`/`shots`/`shot_characters`)+ 任务域(`tasks`)共 9 张表与 Alembic 迁移,字段对齐 [`database.md §3.4–§3.8`](../../../docs/tech-solution/database.md);复用 M0 ORM 约定。
- LangGraph 分析图(`graphs/analysis_graph.py`)+ `analysis/`(state/nodes/prompts),结构化输出经 pydantic 强约束;节点仅消费 `core/llm` 的 `TextModel`。
- `core/llm` 文本接缝首次真实调用:`litellm_text.chat()` 实现 + 门禁/错误映射复用 M1(`require_active_text`→`ModelNotConfigured`、401/403→`invalid`+`ProviderAuthFailed`、429/超时有限重试)。
- 进程内任务执行器(`tasks/`):每用户 Semaphore 并发 + 全局上限 + 排队、启动 `running→interrupted` 恢复、进度回调写记录、协作式 cancel、优雅 shutdown;**M2 开放最小 `POST /api/tasks/:id/cancel`**(解「卡死任务无法重发」陷阱)。
- 剧目/剧本/角色/分析/分镜 REST API(Bearer + 强制隔离)+ 单任务轮询 `GET /api/tasks/:id`(REST 基线);拆解/优化为异步任务。
- analysis 版本化与剧本同构:`analyses.script_version_id`(基于哪版剧本)+ `episodes.current_analysis_id`(当前生效分析);重分析保留旧 analysis 可切回、分镜就地编辑、陈旧性标记不自动作废(D11)。
- 剧本 AI 优化(`optimize`)限定 **copy-edit**(格式/错别字/标点/对白润色),不做 restructure(节奏/结构归拆解 pacing);diff 归后端 `difflib`、前端只读 view、采纳整版(D12)。
- 前端剧库(替换占位)+ 剧集工作台(剧本输入/版本/优化比对、角色预置、发起拆解 + 轮询)+ 分镜编辑台(编辑/拆/合/排序);复用 Zustand + 手动 `request()`,不引 TanStack Query。

**Non-Goals:**

- **视觉素材 / 视频 / 合并 / 导出(FR-A7~A10)**:属 M3/M4。本期 `media` 表不建、`episode_characters.image_media_id` 不落列(形象参考随 M3 `media` 一起加);`storage/FileStore`、`api/{media,video,render,export}` 不实现。分镜的「对白」以**文本**保留,无图/视频/音频。
- **任务中心完善(FR-A11 完整)**:跨剧集聚合列表 `GET /api/tasks`、`POST /api/tasks/:id/retry`、WebSocket `/ws/tasks` 实时推送、任务中心页(TasksPage)均属 **M5**。本期落「任务记录 + 执行器 + 单任务 REST 轮询 `GET /api/tasks/:id` + 最小 `POST /api/tasks/:id/cancel`」,使拆解/优化可异步、可回来查、卡死可取消;**`retry`、聚合列表、WS、任务中心页仍 M5**(D4)。
- **角色库与库↔剧集双向流转(FR-L)**:`library_characters` 表、promote/clone 属 M4。本期 `episode_characters.source` 支持 `preset`/`analysis` 两值(`library` 值与 `source_library_id` 列随 M4 落)。
- **角色自动合并建议引擎**:名称归一化 + 相似度匹配 → 合并建议 + 确认 UX 推迟至 **M4**(随角色库一起做)。M2 拆解产角色仅落库标 `source='analysis'`、与预置角色并列展示,去重由用户经现有角色 CRUD 手动完成(见 D7)。
- **公共角色库引入**:`fromLibraryId` 引入路径属 M4;本期角色仅「用户预置」+「拆解产出」两源。
- **剧本生成(FR-G)/ 多角色模拟(FR-S)**:本期不做,结构位不建(`graphs/{generation,simulation}` 不落)。
- **音频 / 字幕 / 转场**:成片无声、不叠字幕(且成片本身 M4);分镜对白仅文本。
- **LangGraph checkpointer(长流程断点续跑)**:本期靠任务记录 + 重试/单步重做;拆解图不接 MySQL checkpointer(见 [`architecture §7`](../../../docs/tech-solution/architecture.md))。
- **批量成本预估 / 配额计费**:批量生成前成本确认门属 M3+;本期 `tasks.trigger` 字段落 `single`(枚举含 `batch` 但本期不触发批量)。
- **分镜的细粒度历史版本表**:剧本走 `script_versions`、分析走 `analyses` 版本化(D11),两者均 append-only + current 指针;但**分镜本身为就地编辑**(无 `shot_versions` 表,编辑只作用于 current analysis 的 shots,见 D5/D11)。剧本段落级 diff 的细粒度版本同此 Non-Goal。

## Decisions

**D1 归属校验链:episode 经 `drama→user` 二级校验;所有子资源(剧本/角色/分析/分镜)仓储先验 episode 归属再操作;dramas/episodes 软删。** `dramas`/`episodes` 带 `user_id`(dramas 直接带;episodes 经 `drama_id` 间接归属,查询 `JOIN dramas WHERE dramas.user_id=:uid`)。`episode_repo` 的 `get(user_id, episode_id)` 内部校验 `episode→drama→user` 链;`script_repo`/`episode_character_repo`/`analysis_repo`/`shot_repo` 的方法签名一律 `(user_id, episode_id, ...)`,先经 `episode_repo` 验归属(或 JOIN),无命中→`NotFound`→接口 404。dramas/episodes 用 `deleted_at` 软删([`database.md §3.4`](../../../docs/tech-solution/database.md)),软删后子资源查询自然排除(列表/详情带 `deleted_at IS NULL`)。对齐 [`database.md §5`](../../../docs/tech-solution/database.md)、M0 D6。*替代*:① 子资源表冗余 `user_id`(冗余写入、一致性负担,且 episodes 已是归属跳板,无需);② 仅应用层校验不靠 JOIN(查询次数翻倍);③ 物理外键 `ON DELETE CASCADE`(本期软删,不级联物理删)。

**D2 LangGraph 分析图:`START → extract_characters → fan-out(analyze_plot | analyze_conflict | analyze_pacing) → split_shots → END`;结构化输出经 pydantic + 文本模型的 JSON Schema / tool-calling 强约束。** 拆解是「多步骤、有依赖、需进度」的任务:角色抽取是后续三步的输入(fan-out 前置 barrier),情节线/冲突/节奏三者**相互独立可并行**,最后切分镜依赖四维全齐——契合 LangGraph 的状态图 + 并行节点。状态 `AnalysisState(TypedDict)`([`backend.md §5`](../../../docs/tech-solution/backend.md))贯穿:节点读/写状态字段。**结构化约束**:`core/llm` 接缝保持 `chat(messages, **params) -> str` 不变(`response_format`/tool-calling 经 `**params` 透传;接缝**不引入**结构化返回类型——分层对称:接缝不懂 analysis、analysis 不懂 provider);每个节点用 pydantic 模型描述期望输出,把 `response_format` 透传给 `chat()`、对返回的原始 JSON 字符串在 `analysis/` 层做 pydantic 解析校验,避免自由文本解析的脆弱。节点**仅**消费 `TextModel`,不 import litellm(NFR-2,分层自检)。*替代*:① 一次大 prompt 出全部四维(单点失败、超长上下文易漏项、无法并行、进度粒度粗);② 纯 `asyncio.gather` 手写编排(失去 LangGraph 的状态流转/重试/流式事件/未来生成·模拟图统一范式,见 [`backend.md §5`](../../../docs/tech-solution/backend.md));③ 自由文本 + 正则解析(脆、供应商输出差异大)。选 LangGraph 为「并行 fan-out + 结构化 + 可流式 + 与未来图统一」。

**D3 拆解/优化经任务执行器异步执行:`POST /analyze`/`/script/optimize` 落 `pending`→入队→`running`→`succeeded/failed`;前端轮询。** 文本拆解是多节点串行 LLM 调用、耗时在**数十秒到分钟级**,同步阻塞 HTTP 请求会撞 uvicorn 超时、占连接、无法回传进度。发起时:校验门禁(文本模型已配 + 剧本已输入)→ 建 `tasks` 记录(`type=analyze|optimize`,`status=pending`,`input_snapshot` 含剧本版本 + 模型配置快照)→ `executor.submit`→ 返回 `task_id`(202)。前端轮询 `GET /api/tasks/:id`(进度/阶段/状态)与 `GET /api/episodes/:id/analysis`(succeeded 后取结构化结果)。**同一剧集同时只允许一个 `running`/`pending` 的 analyze 任务**(D8 串行约束),重复发起 → 409 `invalid_state`;**卡住的在途任务可经 `POST /api/tasks/:id/cancel` 取消(D4),`canceled`/`failed`/`interrupted` 后即可重新发起 analyze**(解「无 cancel 则卡死」陷阱)。*替代*:FastAPI `BackgroundTasks`(无持久化、进程重启丢失、无并发上限/排队/进度记录,违 FR-A11「可关页面回来」);同步执行(超时、无进度)。

**D4 任务执行器(M2 雏形)范围:每用户 `Semaphore(max_tasks_per_user)` + 全局协程上限 + 排队 `pending`;启动 `running→interrupted`;进度回调写记录;优雅 shutdown。明确不含 WS 广播、cancel/retry REST、`/api/tasks` 聚合列表(均 M5)。** `TaskExecutor` 持每用户 `asyncio.Semaphore`(默认 3–5)与全局 `asyncio.Semaphore(max_global_workers)`;`submit` 落 `pending` 后 `asyncio.create_task(_run)`,`_run` 内 `acquire` 用户信号量(超限自然排队)→置 `running`→执行 `work` 闭包(service 注入,封装调图/落产物)→`succeeded`(写 `output_refs`)/`failed`(写 `error={code,message,details}`)/`canceled`(`CancelledError` 路径)。`recover.py` 在 lifespan 启动期 `UPDATE tasks SET status='interrupted', error={code:'restart_interrupted'} WHERE status='running'`(对齐 [`architecture §4.4`](../../../docs/tech-solution/architecture.md));`shutdown()` 取消在跑协程、落 `interrupted`。进度回调 `progress.py`:`_progress_cb(task_id)` 返回闭包,work 内调用 → 更新 `tasks.progress`/`stage`(写记录,REST 可读)。**本期执行器构造不接 `FileStore`**(M2 无富媒体;M3 引入 `media` 时扩展构造签名注入)。cancel 能力内建(供 shutdown)且 **M2 开放最小 `POST /api/tasks/:id/cancel`**(协作式 `Task.cancel()`,已落地产物保留、置 `canceled`)——解「LLM 调用卡住 → 同剧集无法重发 analyze」陷阱(见 D3);**`retry` REST、聚合列表、WS 仍 M5**。对齐 [`backend.md §7`](../../../docs/tech-solution/backend.md)。*替代*:Celery/RQ(本期单实例过重、需 broker,见 [`总纲 §6`](../../../docs/README.md);`executor.submit` 接口预留以便 M5+ 外移)。

**D5 分镜拆/合/排序:单事务内 dense-rank 重排 `seq`(消除空洞);split 在指定镜后插入并重排;merge 合并相邻两镜、删其一、重排;`target_duration` 3–15s 仅软校验/提示(不阻断编辑)。** `shots.seq` 为排序键,`PATCH`(改字段)、`split`(一镜→多镜)、`merge`(相邻两镜→一镜)、上/下排序均在**单事务**内完成并对该 `episode_id` 下所有镜 `seq` 做 dense-rank 重排(避免删除/拆分留下空洞或重复 seq,保证 `(episode_id, seq)` 唯一有序)。`split` 时:原镜内容拆为 N 段(用户指定切点或默认二分),各段作为新 `description`/`dialogue`,重排。`merge` 时:取相邻两镜(须同 episode、seq 相邻),合并 `description`/`dialogue`、`target_duration` 相加、出场角色取并集,删其一,重排。`target_duration` 3–15s 约束([`analysis §5.1`](../../../docs/requirements/features/analysis.md))由**文本模型在切分时估算**;用户编辑后若越界(拆/合/改时长导致 <3 或 >15),后端**不阻断保存**,仅在响应/前端标注「过短/过长」提示待人工确认(对齐 §5.1 的「合并或标注待确认」语义)。分镜**就地编辑**(无版本表,见 Non-Goals)。对齐 [`database.md §3.6`](../../../docs/tech-solution/database.md) 注。*替代*:① 保留 seq 空洞(查询排序仍可,但 `(episode_id,seq)` 唯一约束被破坏或 seq 不连续,前端展示怪异);② 用浮点 seq 插值(LinkedIn 式,但浮点精度与多次拆分后需重排,复杂度高);③ 3–15s 硬阻断(违「人工确认」语义、阻碍编辑流)。

**D6 剧本版本:不可变追加(`script_versions`) + `scripts.current_version_id` 指针;AI 优化产出 `source='optimize'` 新版本,「接受」=移指针,「拒绝」=不动指针(版本仍保留);PUT 写剧本亦可产 `source='input'` 版本。** `script_versions` 行不可变(append-only),`scripts.current_version_id` 指向当前生效版本。`POST /script/optimize`(异步任务,`type=optimize`)取当前版本内容→LLM **copy-edit** 优化(格式/错别字/标点/对白润色,**不做 restructure**,见 D12)→产出新 `script_versions`(source='optimize')→任务 succeeded 返回新版本 id + 与当前版本的比对(段落级 diff)→用户「接受」(移动 `current_version_id`)/「拒绝」(不动指针,版本仍可回看);**采纳粒度为整版**(前端只读 diff view、不做段落级部分采纳,见 D12)。`PUT /episodes/:id/script` 写入或大改剧本时亦产 `source='input'` 新版本(保留输入历史,可回退)。回退 = 移 `current_version_id` 到任意历史版本。对齐 [`analysis §4.1/§6`](../../../docs/requirements/features/analysis.md)、[`database.md §3.4`](../../../docs/tech-solution/database.md)。*替代*:① 剧本就地覆盖(无版本/比对/回退,违 FR-A3);② 每次编辑都产版本(噪声大;本期「显著改写」才产版本,字段级 PATCH 不产);③ 用 Git 式 diff 存储(diff 重放复杂,append-only 全文 + 段落 diff 计算更简单)。

**D7 角色:预置(`source='preset'`)与拆解产出(`source='analysis'`)都落 `episode_characters`,两源并列展示、由用户经角色 CRUD 手动去重;自动合并建议引擎推迟至 M4。** `extract_characters` 节点产出的角色由分析 service 写入 `episode_characters`(source='analysis');预置角色由 `POST /episodes/:id/characters` 写入(source='preset')。M2 **不做**名称相似度自动匹配/合并建议/确认 UX([`analysis §4.2`](../../../docs/requirements/features/analysis.md) 的「提示合并」),`source` 标记让两源在前端可区分,去重交给用户经现有 CRUD(删/改)手动完成。自动合并建议(归一化 + 相似度阈值)随 **M4** 角色库一起做。对齐 [`analysis §4.2`](../../../docs/requirements/features/analysis.md)。*替代*:① M2 就做建议引擎(阈值敏感、UX 表面大、用户价值低,推迟更划算);② 角色只存 JSON 不建表(失去 CRUD/排序/未来形象绑定,违 [`database.md §7`](../../../docs/tech-solution/database.md));③ 自动去重(误并风险,角色是创作核心资产,否)。

**D8 `core/llm` 文本 `chat()` + 门禁与错误映射(复用 M1 接缝,M2 首次真实路径);同一剧集拆解串行(并发任务仍受执行器限流)。** `analysis_service.analyze(user_id, episode_id)`:`require_active_text(user_id)`(M1 预留)取 active 文本配置→`crypto.decrypt` 取明文 Key(仅驻内存)→`llm_factory.build(snapshot, plaintext_key)` 构造 `TextModel`→拉起分析图,节点内调 `TextModel.chat(...)`。供应商 401/403 → `model_config_service.set_status(invalid)` + 抛 `ProviderAuthFailed`(任务 `failed`,error.code=`provider_auth_failed`);429/超时 → `_probe_with_retry` 式有限重试(M1 已实现探测重试;`chat()` 复用同款有限重试 + 指数退避,超限抛 `RateLimited`)。`analysis/`、`graphs/` **不 import** litellm/crypto(分层自检,grep 无命中)。**并发**:执行器每用户信号量已限全局并发;额外地,**同 episode 同时仅一个 `analyze` 任务**(D3),避免对同一剧本并发拆解产生竞争结果;不同 episode / 不同用户可并发。对齐 [`backend.md §6`](../../../docs/tech-solution/backend.md)。*替代*:① analysis 直接 import litellm(违 NFR-2,否);② 每次节点调用重新构造 TextModel(重复解密,无谓开销;构造一次贯穿图);③ 同 episode 允许并发拆解(结果竞争、产物覆盖,无业务价值)。

**D9 `analyses.result` JSON 结构定型 + shots 拆表 + `config_snapshot`;分镜与四维可追溯。** `analyses.result = {characters:[{name,role_type,persona,motivation,traits,appearance_desc?}], plotlines:[{name,type,scenes,trend}], conflicts:[{type,parties,intensity,resolution}], pacing:{structure,climax,density,imbalance?}}`(pydantic 模型校验,见 D2)。**shots 拆独立表**([`database.md §7`](../../../docs/tech-solution/database.md):需编辑/拆合/排序的拆表,JSON 内更新难),`shots.related_plotline`/`related_conflict` 存名称引用以可追溯。`config_snapshot` 存发起拆解时的文本模型快照(provider/model,params),运行中用户改配置不影响在途任务(承接 [`ai-config §7.4`](../../../docs/requirements/features/ai-config.md))。拆解 succeeded 时:`analyses.status=succeeded` + 写 `result` + 批量插入 `shots`/`shot_characters` + 拆解产角色写 `episode_characters`(D7)。*替代*:四维也拆表(`plotlines`/`conflicts`,[`database.md §9`](../../../docs/tech-solution/database.md) 待定)——本期作为分析快照整体读、无独立 CRUD/检索需求,JSON 足够,演进时再拆(对齐 [`database.md §7`](../../../docs/tech-solution/database.md) 权衡)。

**D10 隔离与越权 404 范式全量承接 M0 D6;前端复用 M0/M1 Zustand 范式(不引 TanStack Query)。** 所有新仓储方法签名带 `user_id`,内部 `WHERE ... AND user_id`(或经 episode→drama→user JOIN,见 D1),跨用户访问一律 404(不泄露存在)。前端剧库/工作台/分镜台用 Zustand store + 手动 `request()`(401 自动刷新拦截内建,复用 M0),发起拆解后**轮询** `GET /api/tasks/:id`(指数退避 2–5s,随阶段动态;running 高频、pending 低频),succeeded 后拉 `GET /analysis` 与 `GET /shots`。**不引 TanStack Query**(用户裁定,与 M0/M1 一致、免新依赖)。`DramasPage` 实现版替换占位;`LibraryPage`(M4)/`TasksPage`(M5)维持占位。对齐 [`frontend.md`](../../../docs/tech-solution/frontend.md)、[`architecture §3.1/§4.5`](../../../docs/tech-solution/architecture.md)。*替代*:① REST 流式 `GET /episodes/:id/stream`([`architecture §3.3 ⑦`](../../../docs/tech-solution/architecture.md))——本期轮询已满足「雏形」,stream 端点随 M5 WS 一起落;② TanStack Query(用户已否)。

**D11 analysis 版本化 + current 指针(与剧本同构):`analyses` 加 `script_version_id` 记录「基于哪版剧本」,`episodes` 加 `current_analysis_id` 指针指向当前生效分析;重分析 = 新 analysis + 新一批 shots + 移指针(旧的保留可切回),分镜就地编辑只作用于 current analysis 的 shots。** 与 `scripts.current_version_id` / `script_versions` 完全同构——同一套 append-only + 指针心智模型用到第二次。`analyses.script_version_id`(FK→script_versions)在发起拆解时写入(= 当时 `scripts.current_version_id`),用于陈旧性判断;`episodes.current_analysis_id`(nullable,FK→analyses)**为避免与 `analyses.episode_id` 循环外键,不加物理 FK、仅 BIGINT NULL 逻辑指针**(归属由应用层/`analysis_repo` 把关,与 M0/M1 隔离范式一致)。「当前分镜清单」= `current_analysis_id` 名下的 shots,`GET /shots` 无歧义。重分析 succeeded → 新建 analysis(记 script_version_id)+ 新一批 shots + 移 `current_analysis_id`;旧 analysis 及其 shots **保留为只读历史**,经 `PATCH /api/episodes/:id/analysis/current` 可切回,用户手编不丢(解「重分析冲手编」)。**陈旧性**:剧本 `current_version_id` 变化(accept optimize / revert)后,`current_analysis.script_version_id ≠ scripts.current_version_id` → `GET /analysis` 返回 `stale_flag=true`,前端标「⚠️ 此分镜基于旧版剧本,建议重新拆解」,**不自动作废**(用户可能有意对照旧分镜);重分析成功后 current 自动切到新 analysis 并提示「可切回」。`GET /analysis` 为双语义:`{current_analysis, inflight_task?, stale_flag}`(既要表达「正在跑」又要表达「上次结果」+「是否陈旧」,工作台刷新进来即知)。分镜**就地编辑**(无 shot_versions 表,见 Non-Goals/D5)。对齐 [`database.md §3.4/§3.6`](../../../docs/tech-solution/database.md)(apply 阶段给 episodes/analyses 各补一列)。*替代*:① A 重分析即作废旧 shots(用户手编被冲,否);② C shots 与 analysis 解耦、episode 级单份(丢「基于哪版剧本」溯源,且重分析=重置需强确认,否);③ 给 `analyses.status` 加 `superseded` 值(靠 current 指针已能区分,多一状态反增歧义,否)。

**D12 `optimize` 范围切分:仅 copy-edit(格式/错别字/标点/对白润色),不做 restructure(节奏/结构重写);diff 归后端 `difflib`、前端只读 view、采纳整版、存储零增量。** FR-A3 §4.1 把「优化」列成四类——前三类(格式规范化/错别字·标点/对白润色)是 **copy-edit**(低改写、保段落结构),「节奏/结构建议」是 **restructure**(高改写、打乱段落对应)。一次 `optimize` 同做两类 → 产出「改了错字 + 顺便把第二幕提前」,diff 满屏且段落对应错乱 → accept/reject 退化为「全要/全不要」、「部分采纳」形同虚设。且 §4.1 对后者用「**建议**」——本属 **advisory**(不改文本),洞察又与拆解的 `analyses.result.pacing`(幕结构/失衡诊断,D9)重叠:optimize 再做是第二次、更粗糙地重复。故切分:**M2 `optimize` 仅 copy-edit**;结构/节奏归拆解 pacing(描述性诊断 + advisory)。**diff 归后端、前端只读**:任务 succeeded 时后端用标准库 `difflib` 按段落算 diff(`[{seg,before,after,change_type}]`;段落切分:plain 按空行、markdown 按段落/标题、fountain 按场景头,`script_service` 小函数,**不引 fountain parser**),经 `output_refs` 返回、**不落库**(临时);前端只渲染只读 diff viewer,**不做段落级勾选/部分采纳**——采纳整版(接受→移 `current_version_id`;拒绝→不动指针、版本保留可回看/回退)。**存储零增量**:仍只产一个新 `script_versions(source='optimize')`,**不加 `suggestions` 字段**;restructure 不落库(归 pacing)。对齐 FR-A3(copy-edit 切片)、D6(版本指针)、D9(pacing 维度)。*替代*:① copy-edit + restructure 同做(diff 失控、部分采纳无意义、与 pacing 重复,否);② optimize 另出 advisory 结构建议(需独立建议 UI+存储、与 pacing 重叠,M2 不值,推 M3+);③ 前端段落级部分采纳(copy-edit 保结构后用户多整版采纳,前端勾选 UI 负担重,M2 不做,留 M3+ 视反馈);④ diff 落库(临时比对无需持久、版本已 append-only 可回看,否)。

**D13 拆解产角色的数据流:`AnalysisState` 内角色以 name 引用、落库事务内才解析为 `episode_character_id`;name 归一化匹配(preset 优先)、失败跳过 + warning;此为外键解析而非角色 dedup(D7 不变)。** 图执行期(纯内存)extracted 角色尚未落库、无 `episode_character_id`,而 `split_shots` 需为每镜标「出场角色」——存在引用键空洞。解法:`AnalysisState` 内角色一律以 **name** 为引用键(`preset_characters` 带 `episode_character_id`、`characters`(extracted)与 `shots[*].appearing` 仅 name);任务 succeeded 落库事务内:先 `bulk_create` extracted 角色(`source='analysis'`)拿回 id → 建 `name→episode_character_id` 全集映射(preset + extracted)→ 逐 shot 解析 `appearing` 写 `shot_characters`。**边界**:这是 shot→character 的**外键解析**,非 D7 的角色合并/去重 —— extracted 角色照常**全部**插库(一行不删),name 映射只决定 shot 链到哪个 id;同名时 **preset 优先**(用户明确建的优先),extracted 同名行作为独立行保留(仅未被该 shot 引用),用户仍见两行可手动合并(D7 不变)。**失败兜底**:LLM 输出 name 与清单漂移(别名/拼写)→ name 归一化(trim/lower/去标点)匹配不上 → **跳过该 shot 的该角色关联 + warning**(shot 本身完整、不阻断落库;用户可经 `PATCH /api/shots/:id` 手动补);M4 随合并引擎升级为相似度 + local_id。`local_id`(c1/c2…)仅作 state 内部稳定键(同名消歧、节点间引用),**不暴露给 LLM、不落库**。对齐 D2(state 流转)、D7(不自动合并)、D9(succeeded 落库)。*替代*:① `split_shots` 直接输出 `episode_character_id`(extracted 未落库、无 id,不可能);② `extract_characters` 节点内即落库拿 id(破坏「失败不留半截产物」D9、节点耦合 DB 违分层,否);③ `shot_characters` 冗余 name 列、id 可空(name 漂移仍孤儿、冗余,否);④ 落库时严格 name 匹配、失败跳过(推荐)。

```mermaid
sequenceDiagram
    autonum
    participant E as TaskExecutor
    participant G as analysis_graph
    participant EC as extract_characters
    participant F as fan-out(plot/conflict/pacing)
    participant SS as split_shots
    participant SVC as analysis_service.persist
    participant DB as episode_characters / shots / shot_characters

    rect rgb(235, 248, 255)
    Note over E,SS: 图执行期 — 纯内存,extracted 角色无 db id,统一以 name 引用
    E->>G: run(AnalysisState)
    G->>EC: extract
    EC-->>G: state.characters = [小明, 阿珍, ...]  (extracted, 无 id)
    G->>F: barrier — 角色作为后续三步输入
    F-->>G: plotlines / conflicts / pacing
    G->>SS: split
    SS-->>G: state.shots.appearing = [小明, 阿珍]  (name 引用)
    G-->>E: done(state)
    end

    rect rgb(255, 246, 236)
    Note over SVC,DB: 落库事务 — succeeded 才落,失败/取消不留半截 (D9)
    E->>SVC: persist(state)
    SVC->>DB: ① bulk_create extracted (source=analysis)
    DB-->>SVC: 返回 ids → 建 name→id 映射 (preset 优先)
    SVC->>DB: ② bulk_create shots
    SVC->>DB: ③ appearing 经 name→id 解析 (失败跳过+warning) → shot_characters
    SVC-->>E: committed
    end
```

## Risks / Trade-offs

- **[LangGraph 结构化输出依赖供应商 JSON/tool 支持度不一]** → 并非所有文本模型都稳健支持 `response_format`/tool-calling。*缓解*:`core/llm` `chat()` 优先用 `response_format`(OpenAI 兼容),不支持者退化为「提示词要求 JSON + pydantic 解析 + 失败有限重试」;pydantic 校验失败 → 任务 `failed`(error.code 标 `analysis_parse_error`),用户可重试;提示工程在 `analysis/prompts.py` 集中维护、可按 provider 调整。
- **[任务执行器在内存,进程重启丢在跑协程]** → 拆解/优化任务会中断。*缓解*:`recover.py` 启动扫描置 `interrupted`(error.code=`restart_interrupted`),前端轮询见 `interrupted` 提示「可重试」;本期不自动续跑(单步重做/重发起成本可接受,见 [`architecture §4.4`](../../../docs/tech-solution/architecture.md));M5 引入 retry 端点后体验更顺。
- **[同 episode 串行拆解的并发约束需应用层把关]** → 仅靠执行器信号量不限「同 episode」。*缓解*:`analyze` 发起时 `analysis_repo.has_inflight(user_id, episode_id)`(查 `pending`/`running` 的 analyze 任务)→ 有则 409 `invalid_state`;UNIQUE/部分索引 MySQL 不支持,用应用层 + 查询保证(与 M1 active 唯一性的应用层兜底同思路)。
- **[角色去重全靠手动]** → M2 不做自动合并建议,预置与拆解产角色可能重复,用户需手动去重。*缓解*:`source` 标记让两源在前端可区分、去重经现有 CRUD 几步完成;自动合并建议(相似度匹配)留 M4。
- **[9 张表一次迁移体量大、autogenerate 偏移风险]** → 生成列/外键/枚举集合多。*缓解*:迁移手写/校准(复用 M0/M1 经验:drop_table 前删冗余 drop_index、枚举值集对齐模型、外键 `ON DELETE` 按语义),在 env 配置的外部 MySQL 上 `upgrade`/`downgrade` 双向验证;表按域分组、模型先 re-export 再 autogenerate。
- **[分镜 3–15s 软校验可能产出无效时长组合]** → 用户编辑/拆合后可能全片时长失衡。*缓解*:后端响应标注越界、前端高亮;不阻断保存(尊重人工确认语义);成片合并(M4)时再复核。
- **[前端轮询频率 vs 服务端负载]** → 拆解分钟级、高频轮询浪费。*缓解*:指数退避 2–5s、随 `stage`/`status` 动态(pending 低频、running 中频、近 succeeded 加快);M5 WS 落地后免去轮询。
- **[`analysis.result` 用 JSON 限制跨剧集检索]** → 未来想按角色/情节线跨剧集搜索需拆表。*缓解*:[`database.md §7/§9`](../../../docs/tech-solution/database.md) 已预留 `plotlines`/`conflicts` 拆表演进路径,本期不阻断;演进时迁移(JSON→表,一次性回填)。

- **[分析/分镜历史无限增长]** → 每次重分析 append 新 analysis + 新 shots,旧的不删。*缓解*:本期单用户量级可接受;`analyses`/`shots` 随 episode 软删级联清理;可配「每 episode 保留最近 N 个 analysis」策略(留 M4/M5)。
- **[current 指针与剧本版本不一致的提示边界]** → accept optimize 后 current script 变 v2,但 current analysis 仍基于 v1 → 标陈旧。*缓解*:仅提示不阻断(用户可能有意对照旧分镜改新剧本);切换 analysis 为显式动作,不自动联动。
- **[optimize 不做 restructure 可能与「优化结构」期望不符]** → 用户可能期望 optimize 改善节奏/结构。*缓解*:拆解侧 pacing 维度(幕结构/失衡诊断,D9)已提供结构洞察;optimize 在 UI 文案明示「仅润色文本(格式/错字/对白),不改结构」;advisory 结构建议(不改文本)随 M3+ 视用户反馈补。

## Implementation Notes(apply 实施指引)

> apply 阶段的实施约束与模式指引:承接 M0/M1 既有范式,并落实「设计模式 + prompt 工程 + 模块化能力(strategy/skills)」。

### 模式分层(承接 M0/M1,M2 延用)

- **Repository**:`db/repositories/*_repo.py` 封装全部 SQL,签名一律带 `user_id`、强制隔离与越权 404(D1/D10);M2 新增 drama/episode/script/episode_character/analysis/shot/task 七个 repo。service 层**不写裸 SQL**。
- **Service / 用例编排(事务边界)**:`services/*_service.py` 编排 repo + `core/llm` + 执行器,**事务边界在 service**(repo 只 flush 不 commit,承接 M0 D14);M2 新增 drama/episode/script/analysis/shot service。
- **Factory**:`llm/factory.build(snapshot, plaintext_key) -> TextModel`(M1)按用途/供应商构造;analysis_service 复用之构造**贯穿整图的单个** `TextModel`(D8,避免逐节点重复解密)。
- **Adapter(供应商无关接缝)**:`core/llm` 是适配层;`graphs`/`analysis` **仅依赖 `TextModel` Protocol,绝不 import litellm/厂商 SDK**(NFR-2,分层 grep 自检)。

### Strategy = 模块化能力(skills)

把每项 LLM 能力做成**可插拔策略**;新增能力 = 新增一个策略实现,**不动图骨架与 core/llm 接缝**:

```python
class PromptStrategy(Protocol):
    name: str
    def build_messages(self, ctx: AnalysisState) -> list[Mapping[str, str]]: ...  # 提示构造
    output_model: type[BaseModel]                                                  # 期望结构化输出
    def response_format(self, provider: str) -> dict | None: ...                   # 按 provider 选 JSON/tool/退化
    def parse(self, raw: str) -> BaseModel: ...                                    # 解析 + JSON 修复 + pydantic 校验
```

- 5 个拆解节点 + optimize(copy-edit)各持一个 `PromptStrategy` 实例;`analysis/prompts.py` 从「裸字符串函数」**升级为策略对象集合**。
- 节点本身只编排:读 `AnalysisState` → 策略 `build_messages` → `TextModel.chat(messages, **{response_format})` → 策略 `parse` → 写 state;**节点不掺 prompt/解析细节**。
- 这让「能力」可插拔、可单测、可按 provider 调整,并把 D2「接缝返回 `str`、结构化解析在 analysis 层」落到策略 `parse()`(承接 5.5 spike 的铠甲轻重)。

### Prompt 工程

- **集中管理**:所有提示在 `analysis/prompts.py`(策略对象内),不散落节点/service;可 review、**不含明文 Key**。
- **provider 适配**:`response_format`/tool-calling 支持度因供应商而异(D2 风险);**策略层决定**用哪种结构化约束,并承载退化路径(提示词 JSON + pydantic + 有限重试),失败统一映射 `analysis_parse_error`。
- **copy-edit 与拆解提示分离**(D12):optimize 策略明示「仅润色(格式/错字/对白),不重写/重排/结构调整」;拆解各节点策略按维度。两类不混。
- **角色清单约束**(D13):`split_shots` 策略的 prompt 含「已知角色名清单(preset + extracted)」,要求 appearing 从清单选、输出 name(不输出 db id)。

### 事务与一致性

- service 为事务边界;落库(D13)「bulk_create extracted → name→id 映射 → shots → 解析 appearing → shot_characters」在**单一事务**内,任一步失败整体回滚(不留半截产物,对齐 D9)。

## Migration Plan

**首次部署(M2):**

1. 后端:`cd backend && uv sync`(新增 `langgraph`)→ `alembic upgrade head`(建 9 张表:dramas/episodes/scripts/script_versions/episode_characters/analyses/shots/shot_characters/tasks;含 D11 的 `analyses.script_version_id`(FK→script_versions)+ `episodes.current_analysis_id`(为避免循环外键不加物理 FK、仅逻辑指针);复用 M0/M1 外键与 ORM 约定)→ 重启服务(lifespan 内 `executor.recover_running()` 首次为空跑,无副作用)。
2. 前端:`cd frontend && npm install`(无新依赖)→ `npm run dev`(`DramasPage` 实现版 + 剧集工作台 + 分镜编辑台随路由生效)。
3. 验证:注册/登录(已配文本模型)→ 建剧 → 建剧集(设画幅/风格)→ 输入剧本(可选 AI 优化:发起→轮询→比对→接受/拒绝)→ 预置角色 → 发起拆解 → 轮询 `GET /api/tasks/:id` 见 `running`→`succeeded` → 取 `GET /analysis`(四维)+ `GET /shots`(分镜清单)→ 编辑分镜(改字段/拆/合/排序)→ 越权访问他人剧集/分镜 → 404。

**回滚(仅开发期):** `cd backend && alembic downgrade <prev>` 删除 9 张表;移除 `graphs/`、`analysis/`、`tasks/`、新表模型/仓储/service/api、前端剧库/工作台/分镜台;`DramasPage` 回退占位;`langgraph` 依赖移除。生产走向前迁移 + 兼容期,不做破坏性回滚。

## Open Questions

- **结构化输出的供应商兜底**:是否需要一个「provider → 是否支持 response_format」的显式注册表(而非 try/except 退化)?本期按「优先 response_format、失败退化为提示词 JSON + 重试」实现;若 provider 增多且退化路径不稳,再抽注册表(随 M3 视频接入一起定)。
- **轮询频率基线**:2–5s 的具体档位随 `stage` 如何取值?(建议 pending=5s、running=3s、stage 切换瞬间=2s;M5 WS 后废弃)。
