# 数据库设计(drama-smith)

> 版本:v0.1 · 状态:实施型 · 最近更新:2026-06-30
> **定位**:承接 [`architecture.md`](./architecture.md)(资源域与契约)与 [总纲](./README.md)(默认决策),本文落 **ER 模型、表结构、索引、约束、隔离实现、加密字段、JSON 字段、迁移**。ORM = SQLAlchemy 2.0(async,asyncmy)+ Alembic;数据库 = MySQL 8(utf8mb4)。表 DDL 由 Alembic 迁移生成,字段级类型以 SQLAlchemy 模型为准。
> **核心约束**:多租户强制隔离(NFR-7)、凭证加密(NFR-8)、任务可恢复(FR-A11)、用户数据可清理(FR-U3)。

---

## 1. 设计原则

| 原则 | 约定 |
|------|------|
| **多租户隔离** | 每张业务表带 `user_id`(外键→`users.id`)+ 索引;查询在仓储层**强制**带 `user_id` 过滤(见 §5)。资源按 `id+user_id` 定位,越权→应用层 404。 |
| **主键** | `BIGINT UNSIGNED AUTO_INCREMENT` 内部 id(不对外暴露自增语义,前端按 id 操作即可);多对多关联表用复合主键。 |
| **时间戳** | 统一 `created_at`/`updated_at`(`DATETIME(3)`,UTC);可清理资源带 `deleted_at`(软删,见 §5)。 |
| **字符集** | 库/表/列 `utf8mb4`、`utf8mb4_0900_ai_ci`;`VARCHAR` 长度按字段语义定。 |
| **结构化产物** | 整体读写、不单独查询的(分析四维、provider_options、params、task 快照)用 `JSON`;**需单独 CRUD/编辑/排序/选用的**(分镜、媒体)拆为独立表(见 §7)。 |
| **加密字段** | API Key 信封加密:两个自包含 blob(`api_key_ciphertext`/`dek_ciphertext`)+ 脱敏串 `api_key_masked`(见 §6);明文永不落库。 |
| **布尔/枚举** | 枚举用 `ENUM`(值集稳定)或 `VARCHAR`(值集可能扩展,如 provider);布尔用 `TINYINT(1)`。 |
| **外键** | 物理外键约束开启(`ON DELETE` 按语义);用户隔离的归属校验同时在应用层把关。 |

---

## 2. ER 概览

按资源域分组(对应 [`architecture.md §3.3`](./architecture.md) 的端点域):

```
用户域            配置域              角色库域
 users ──┬──► refresh_tokens        model_configs(user_id)
         │
         ├──► library_characters ──► media(image)
         │         ▲ clone(复制)
         │         │ promote(复制)
剧目域   │         │
 dramas ─► episodes ─► episode_characters ──► media(形象参考)
              │
              ├──► scripts ──► script_versions
              ├──► analyses ──► shots ──► shot_characters ──► episode_characters
              │                  └──► media(单镜素材)
              ├──► media(逐镜视频)
              └──► tasks

富媒体域:media(owner_type: shot/character/library/episode;kind: image/video/final)
任务域:tasks(episode_id,type,status,progress,...)
```

**复制语义**(库↔剧集,[FR-L](../requirements/features/character-library.md)):`promote-to-library` 与 `clone-to-episode` 均为**独立复制**,不建引用、不联动;`episode_characters.source` 仅记录来源类型、`source_library_id` 仅作溯源标记(不构成外键强约束)。

---

## 3. 表结构(分域)

> 字段表列:`字段 | 类型 | 约束 | 说明`。`FK u→users` 表示外键到 users 并带索引。

### 3.1 用户域

**users**
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT UNSIGNED | PK, AI | |
| username | VARCHAR(32) | UNIQUE, NOT NULL | 3–32 字母数字下划线([FR-U1](../requirements/features/user-auth.md)) |
| password_hash | VARCHAR(255) | NOT NULL | argon2id 哈希(含盐、参数) |
| failed_login_count | INT | NOT NULL DEFAULT 0 | 失败计数(按账号) |
| locked_until | DATETIME(3) | NULL | 锁定截止;过窗自动解锁 |
| last_login_at | DATETIME(3) | NULL | |
| created_at / updated_at | DATETIME(3) | NOT NULL | |

**refresh_tokens**(可吊销)
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT UNSIGNED | PK, AI | |
| user_id | BIGINT UNSIGNED | FK u→users, INDEX | |
| token_hash | VARCHAR(255) | UNIQUE, NOT NULL | 不透明随机串的哈希(不存明文) |
| expires_at | DATETIME(3) | NOT NULL, INDEX | 默认 +7 天 |
| revoked_at | DATETIME(3) | NULL | 登出/吊销时间;NULL=有效 |
| created_at | DATETIME(3) | NOT NULL | |

> 定期清理:`expires_at < now AND revoked_at IS NOT NULL` 的可归档删除。

### 3.2 配置域

**model_configs**(BYOK;API Key 加密)
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT UNSIGNED | PK, AI | |
| user_id | BIGINT UNSIGNED | FK u→users, INDEX | |
| purpose | ENUM('text','image','video') | NOT NULL | 用途 |
| provider | VARCHAR(64) | NOT NULL | 供应商(白名单,[ai-config §2.1](../requirements/features/ai-config.md)) |
| model | VARCHAR(128) | NOT NULL | 模型标识 |
| base_url | VARCHAR(512) | NULL | 自部署/网关 |
| api_key_ciphertext | VARBINARY(512) | NOT NULL | DEK 加密明文 Key 的自包含 blob `nonce‖ct‖tag`(§6,A2) |
| dek_ciphertext | VARBINARY(512) | NOT NULL | MEK 加密 DEK 的自包含 blob `nonce‖ct‖tag`(信封,§6) |
| api_key_masked | VARCHAR(32) | NOT NULL | 脱敏串(写时落库,读路径不碰 MEK,m2) |
| params | JSON | NULL | 调用默认参数(text:temp/max_tokens;image:size/quality/n;video:duration/resolution/aspect) |
| provider_options | JSON | NULL | 扩展字段(Azure endpoint/api_version/deployment 等) |
| is_active | TINYINT(1) | NOT NULL DEFAULT 0 | 该用途当前生效(每用户每用途恰一条 active,见下方约束) |
| status | ENUM('active','invalid') | NOT NULL DEFAULT 'active' | 运行期 401/403→invalid([FR-C5](../requirements/features/ai-config.md)) |
| last_tested_at | DATETIME(3) | NULL | 自检时间([FR-C3](../requirements/features/ai-config.md)) |
| created_at / updated_at | DATETIME(3) | NOT NULL | |

> **每用途恰一条 active 的保证**(MySQL):生成列 `active_key VARCHAR(128) GENERATED ALWAYS AS (CASE WHEN is_active=1 THEN CONCAT(user_id,'-',purpose) ELSE NULL END) VIRTUAL`,对 `active_key` 建 `UNIQUE` 索引(MySQL 允许多行 NULL,故非 active 行不冲突);切换 active 在事务内翻转两行。

### 3.3 角色库域

**library_characters**(跨剧复用;不去重、允许同名,[FR-L](../requirements/features/character-library.md))
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT UNSIGNED | PK, AI | |
| user_id | BIGINT UNSIGNED | FK u→users, INDEX | |
| name | VARCHAR(64) | NOT NULL | 必填 |
| age | ENUM('unknown','0_6','7_12','13_17','18_30','31_45','46_59','60_plus') | NOT NULL DEFAULT 'unknown' | 年龄枚举(单选) |
| description | TEXT | NULL | 人设/性格/背景 |
| is_protagonist | TINYINT(1) | NOT NULL DEFAULT 0 | 主角/配角 |
| image_media_id | BIGINT UNSIGNED | NULL | 形象图→media(生成或上传) |
| created_at / updated_at | DATETIME(3) | NOT NULL | |

> 索引:(user_id, name) 支持检索;(user_id, is_protagonist) 支持主配角筛选。删除不级联已引入副本。

### 3.4 剧目域

**dramas**
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT UNSIGNED | PK, AI | |
| user_id | BIGINT UNSIGNED | FK u→users, INDEX | |
| name | VARCHAR(128) | NOT NULL | |
| sort_order | INT | NOT NULL DEFAULT 0 | 剧集容器排序 |
| deleted_at | DATETIME(3) | NULL | 软删 |
| created_at / updated_at | DATETIME(3) | NOT NULL | |

**episodes**(剧集 = 流水线容器;画幅/风格整集统一,[§4.4](../requirements/features/analysis.md))
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT UNSIGNED | PK, AI | |
| drama_id | BIGINT UNSIGNED | FK→dramas, INDEX | 归属校验经 drama→user |
| title | VARCHAR(128) | NOT NULL | |
| sort_order | INT | NOT NULL DEFAULT 0 | |
| aspect_ratio | ENUM('16:9','9:16','1:1','4:3') | NOT NULL | 整集画幅(FR-A7/A8 统一约束) |
| style_preset | VARCHAR(64) | NULL | 画面风格基调(枚举或自由,实现定) |
| status | ENUM('draft','analyzing','ready','rendering','done') | NOT NULL DEFAULT 'draft' | 工作台状态 |
| deleted_at | DATETIME(3) | NULL | |
| created_at / updated_at | DATETIME(3) | NOT NULL | |

**scripts**(每剧集一份剧本)
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT UNSIGNED | PK, AI | |
| episode_id | BIGINT UNSIGNED | FK→episodes, UNIQUE | 1:1 |
| current_version_id | BIGINT UNSIGNED | NULL | 指向当前生效版本(可回退) |
| created_at / updated_at | DATETIME(3) | NOT NULL | |

**script_versions**(版本/比对/回退,[FR-A3](../requirements/features/analysis.md))
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT UNSIGNED | PK, AI | |
| script_id | BIGINT UNSIGNED | FK→scripts, INDEX | |
| version_no | INT | NOT NULL | |
| content | MEDIUMTEXT | NOT NULL | 剧本正文 |
| format | ENUM('plain','markdown','fountain') | NOT NULL DEFAULT 'markdown' | [FR-A2](../requirements/features/analysis.md) |
| source | ENUM('input','optimize') | NOT NULL | 输入 / AI 优化产出 |
| created_at | DATETIME(3) | NOT NULL | |

### 3.5 剧集角色域

**episode_characters**(富字段角色;可由预置/拆解/库引入,[FR-A4](../requirements/features/analysis.md))
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT UNSIGNED | PK, AI | |
| episode_id | BIGINT UNSIGNED | FK→episodes, INDEX | |
| name | VARCHAR(64) | NOT NULL | |
| role_type | VARCHAR(32) | NULL | 主角/配角/反派… |
| persona | VARCHAR(512) | NULL | 一句话人设 |
| motivation | VARCHAR(512) | NULL | 动机/目标 |
| traits | JSON | NULL | 性格特质标签 |
| appearance_desc | VARCHAR(1024) | NULL | 形象描述(供一致性生成) |
| image_media_id | BIGINT UNSIGNED | NULL | 形象参考图(跨镜一致,[§5.2](../requirements/features/analysis.md)) |
| source | ENUM('preset','analysis','library') | NOT NULL DEFAULT 'preset' | 来源标记 |
| source_library_id | BIGINT UNSIGNED | NULL | 溯源标记(引入来源,不联动) |
| sort_order | INT | NOT NULL DEFAULT 0 | |
| created_at / updated_at | DATETIME(3) | NOT NULL | |

### 3.6 分析产物域

**analyses**(一次拆解的完整结果与配置快照)
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT UNSIGNED | PK, AI | |
| episode_id | BIGINT UNSIGNED | FK→episodes, INDEX | |
| status | ENUM('pending','running','succeeded','failed') | NOT NULL | |
| result | JSON | NULL | `{characters?,plotlines,conflicts,pacing}`(分镜拆出为 shots 表) |
| config_snapshot | JSON | NULL | 拆解时的文本模型快照 |
| created_at / updated_at | DATETIME(3) | NOT NULL | |

**shots**(分镜清单;可编辑/拆/合/排序,[FR-A6](../requirements/features/analysis.md))
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT UNSIGNED | PK, AI | |
| analysis_id | BIGINT UNSIGNED | FK→analyses, INDEX | 来源分析 |
| episode_id | BIGINT UNSIGNED | FK→episodes, INDEX | 归属冗余(便于列表/校验) |
| seq | INT | NOT NULL | 序号/排序 |
| description | VARCHAR(1024) | NOT NULL | 镜头描述 |
| shot_type | ENUM('wide','medium','close','extreme_close') | NULL | 全/中/近/特写 |
| scene | VARCHAR(128) | NULL | 对应场次 |
| plot_point | VARCHAR(255) | NULL | 剧情点/情绪 |
| dialogue | TEXT | NULL | 对白(文本,本期不配音) |
| target_duration | DECIMAL(5,2) | NULL | 目标秒数(3–15,[§5.1](../requirements/features/analysis.md)) |
| camera_move | VARCHAR(64) | NULL | 运镜(可选) |
| related_plotline | VARCHAR(128) | NULL | 可追溯 |
| related_conflict | VARCHAR(128) | NULL | 可追溯 |
| created_at / updated_at | DATETIME(3) | NOT NULL | |

> 排序:`(episode_id, seq)` 索引;拆/合在事务内重排 `seq`。

**shot_characters**(单镜出场角色,多对多)
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| shot_id | BIGINT UNSIGNED | PK, FK→shots | |
| episode_character_id | BIGINT UNSIGNED | PK, FK→episode_characters | |
| role_in_shot | VARCHAR(32) | NULL | 该镜内角色作用(可选) |

### 3.7 富媒体域

**media**(图/视频/成片统一表;多候选 + 选用;多态归属)
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT UNSIGNED | PK, AI | |
| user_id | BIGINT UNSIGNED | FK u→users, INDEX(user_id,owner_type,owner_id) | |
| kind | ENUM('image','video','final') | NOT NULL | |
| owner_type | ENUM('character','shot','library','episode') | NOT NULL | 多态归属 |
| owner_id | BIGINT UNSIGNED | NOT NULL | 配合 owner_type |
| source | ENUM('upload','generate') | NOT NULL | |
| storage_provider | VARCHAR(32) | NOT NULL DEFAULT 'local' | 本期 'local';预留对象存储 |
| storage_key | VARCHAR(512) | NOT NULL | FileStore 对象键/相对路径 |
| content_type | VARCHAR(64) | NOT NULL | mime |
| size_bytes | BIGINT UNSIGNED | NOT NULL | |
| width / height | INT | NULL | 图/视频 |
| duration_sec | NUMERIC(8,2) | NULL | 视频/成片 |
| selected | TINYINT(1) | NOT NULL DEFAULT 0 | 用户在多候选中选用(合并取此) |
| selected_key | VARCHAR(128) | GENERATED ALWAYS AS (CASE WHEN selected=1 THEN CONCAT(user_id,'-',owner_type,'-',owner_id) ELSE NULL END) VIRTUAL, **UNIQUE** | 单选保证(镜像 model_configs.active_key) |
| status | ENUM('ready','processing','failed') | NOT NULL DEFAULT 'ready' | |
| extra | JSON | NULL | 扩展(尺寸 / 供应商回参等) |
| provider_task | VARCHAR(256) | NULL | 异步供应商任务 id(M3 视频) |
| last_tested_at | DATETIME(3) | NULL | 自检时间(预留) |
| created_at / updated_at | DATETIME(3) | NOT NULL | |

> **单选约束**:生成列 `selected_key` 仅在 `selected=1` 时取 `user_id-owner_type-owner_id`,对其建 `UNIQUE`(MySQL 允许多 NULL,故非选中行不冲突);切换选中在事务内翻旧行为 0 再写新行(避免 UNIQUE 冲突)。索引 `(user_id, owner_type, owner_id)` 列某镜/某角色候选(episode_id 需经 owner 解析)。

### 3.8 任务域

**tasks**(任务中心;持久化、可恢复,[FR-A11](../requirements/features/analysis.md)、[architecture §4.1](./architecture.md))
| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT UNSIGNED | PK, AI | |
| user_id | BIGINT UNSIGNED | FK u→users, INDEX | |
| episode_id | BIGINT UNSIGNED | FK→episodes, INDEX, NULL | 跨剧集汇总跳转 |
| type | ENUM('optimize','analyze','image','video','render') | NOT NULL | |
| status | ENUM('pending','running','succeeded','failed','canceled','interrupted') | NOT NULL | |
| progress | TINYINT UNSIGNED | NOT NULL DEFAULT 0 | 0–100 |
| stage | VARCHAR(64) | NULL | 当前阶段(供 UI) |
| trigger | ENUM('single','batch') | NOT NULL DEFAULT 'single' | |
| input_snapshot | JSON | NULL | 输入 + 模型配置快照([ai-config §7.4](../requirements/features/ai-config.md)) |
| output_refs | JSON | NULL | 产物引用(media/shot/analysis id) |
| error | JSON | NULL | `{code,message,details}` |
| created_at / started_at / finished_at | DATETIME(3) | NULL | 时间线 |

> 索引:(user_id, status, created_at) 任务页过滤;(episode_id) 跳转。

---

## 4. 索引策略(汇总)

- **隔离索引**:所有业务表的 `user_id` 单列索引(列表/过滤主力)。
- **唯一约束**:`users.username`、`refresh_tokens.token_hash`、`scripts.episode_id`(1:1)、`model_configs` 的 `active_key` 生成列唯一(每用途一 active)、`media` 的 `selected_key` 生成列唯一(每 owner 至多一条 selected)。
- **业务索引**:任务页 `(user_id,status,created_at)`;分镜 `(episode_id,seq)`;角色库 `(user_id,name)`/`(user_id,is_protagonist)`;媒体 `(user_id,owner_type,owner_id)`。
- **避免过度索引**:多态 `media.owner_id` 不单独建(随 `(user_id,owner_type,owner_id)` 复合覆盖)。

---

## 5. 用户隔离的实现(双层把关)

1. **DB 层**:每张业务表含 `user_id` 外键 + 索引;`tasks`/`media` 等横切表亦带 `user_id`。
2. **仓储层(强制)**:所有读写在 SQLAlchemy 仓储层封装,查询自动注入 `WHERE user_id = :current_user`;资源定位 `WHERE id=:id AND user_id=:uid`,无命中→上层 404。
3. **接口层**:FastAPI 依赖注入取 `user_id` 注入仓储;无任何"裸 id 跨用户"通路。
4. **富媒体**:不直读路径,经鉴权代理/签名 URL(见 [architecture §5.6](./architecture.md));`media.user_id` 校验归属。
5. **可清理(FR-U3)**:剧/剧集软删(`deleted_at`);媒体/任务等随剧集级联清理或独立清理入口。

---

## 6. 加密字段存储(信封加密 · NFR-8)

承接 [architecture §4.5](../architecture/system-architecture.md) 与 [ai-config §6](../requirements/features/ai-config.md):

- **主密钥 MEK**:经环境变量(`DS_MEK`,base64 32B)注入,**不入库、不入日志**;生产建议接 KMS。
- **每条配置一个 DEK**:随机生成 `data_key`;用 DEK 经 **AES-256-GCM** 加密 API Key → **自包含 blob** `nonce‖ct‖tag`(`api_key_ciphertext`,无单独 iv 列,A2)。
- **DEK 落库**:DEK 经 MEK 加密 → **自包含 blob** `nonce‖ct‖tag`(`dek_ciphertext`,信封);读出时 MEK 解 DEK、DEK 解密文。
- **脱敏**:`api_key_masked`(`sk-…ab12`,前 3 + 末 4)写时落库;列表/读路径不解密、不碰 MEK(m2)。
- **轮换**:换 MEK 时遍历解密→用新 MEK 重封 `dek_ciphertext`(`api_key_ciphertext` 不动)。

---

## 7. JSON 字段设计(取舍)

| 用 JSON(整体读写、不单独查询) | 拆独立表(需单独 CRUD/编辑/选用/排序) |
|---|---|
| `analyses.result`(角色/情节线/冲突/节奏四维,作为分析快照整体读) | `shots`(逐镜编辑、拆合、排序) |
| `model_configs.params` / `provider_options` | `media`(多候选、选用、归属) |
| `tasks.input_snapshot` / `output_refs` / `error` | `episode_characters` / `library_characters`(CRUD、检索) |
| `episode_characters.traits`(标签数组) | `shot_characters`(多对多出场) |

**原则**:JSON 仅用于"随主体整体存取、无独立生命周期"的半结构数据;凡有独立编辑/选用/查询/排序需求的,一律建表(避免 JSON 内更新难题)。

> **权衡点**:`analyses.result` 中的「角色/情节线/冲突/节奏」若未来需跨剧集检索或独立编辑,可再拆表(如 `plotlines`/`conflicts`);本期作为分析快照用 JSON 足够,演进时迁移。

---

## 8. 迁移策略(Alembic)

- 迁移版本入 git(`migrations/versions/`),命名 `<down_revision>_<slug>.py`;每个迁移含 `upgrade()`/`downgrade()`。
- **初始 schema**:M0 里程碑建立 users/refresh_tokens/model_configs;后续里程碑按域增量建表(dramas/episodes/scripts → analyses/shots → media → tasks)。
- **数据迁移**:结构变更与数据回填分离;生成列、唯一索引等需在迁移中显式处理(尤其 `model_configs.active_key`)。
- **回滚**:downgrade 仅用于开发期;生产变更走向前迁移 + 兼容期(新增列先加后用、删除列先停用后删)。
- **测试库**:统一走 env 配置(`DS_DATABASE_URL`/`DS_TEST_DATABASE_URL`);session 夹具自动建 `<db>_test` 库并跑迁移,CI / 本地同源(不另起 testcontainers / docker-compose)。

---

## 9. 待定 / 后续

- **主键策略**:本期 `BIGINT AI`;若需分布式/多实例可切 Snowflake/UUID(迁移成本)。
- **`analyses.result` 拆表**:跨剧集检索角色/情节线时再拆 `plotlines`/`conflicts`(见 §7)。
- **媒体配额与清理**:用户富媒体配额上限、过期/孤立媒体清理策略(视频体积大)。
- **LangGraph checkpointer 表**:若启用断点续跑(architecture §7),需新增 checkpoint 表族(MySQL checkpointer schema)。
- **`style_preset` 值集**:固定枚举 vs 自由文本(随画幅/风格细化定)。
