# 系统需求(drama-smith)

> 版本:v0.10 · 状态:总览(技术实现归 architecture) · 最近更新:2026-06-30
> **定位**:本文档只记项目级**概要**与**未决问题**;各功能点的具体方案、规则、接口、专属待澄清见 `features/` 子文档,**技术实现/选型见 [`architecture/system-architecture.md`](../architecture/system-architecture.md)**,变更级需求与 spec 见 `openspec/`。
> **变更沿革**:v0.2 认证 + 分镜 + MySQL · v0.3 按功能点拆子文档 · v0.4 认证细化(→ user-auth.md)· v0.5 AI 配置门禁 + core/llm 视频适配器(→ ai-config.md)· v0.6 主文档瘦身 · v0.7 NFR 去技术化 · **v0.8 结构化分析扩写为完整生产流水线(剧名/剧集→剧本→拆解→分镜→编辑→视频→合并),音频推迟(→ analysis.md)· **v0.9 新增公共角色库(跨剧复用角色,→ character-library.md)** · **v0.10 analysis 新增任务中心 / 任务页(FR-A11):长任务统一持久化、任务页跨剧集汇总,状态经 REST 轮询 + WebSocket 实时回传(→ analysis.md §4.5)**。

## 1. 项目愿景

drama-smith 是一个**综合性戏剧/剧本创作工具链**,围绕 LLM 能力,把三件事整合到一处:

- **剧本生成(generation)**——从主题/大纲产出完整剧本或分集短剧。
- **结构化分析(analysis)**——对已有剧本做角色、情节线、冲突、节奏的结构化拆解。
- **多角色模拟(simulation)**——定义角色人设,让多个 LLM 角色互动推演剧情。

长期目标是让创作者在一个一致的工程框架内,在"生成—分析—模拟"三者之间自由流转。
**本期(v0.2/0.3)只落地"结构化分析"一个子系统,并先打好"多用户 + 用户自带 AI 配置"的地基。**

## 2. 目标用户与场景

- 短剧/剧本创作者:把已写的剧本喂进来,拿到结构诊断,定位节奏与冲突的问题。
- 编剧/策划:对既有剧本做角色、情节线、冲突、节奏的拆解,辅助改稿与立项评估。
- 创作团队(多用户):多人各自注册账号,用自己接入的模型独立分析,数据互不干扰。
- 创作实验者(后续):用角色模拟探索剧情走向——**本期不实现**。

## 3. 本期范围

| 维度 | 本期是否做 |
|------|--------------------|
| 多用户账号体系(注册/登录/数据隔离) | ✅ 做 → [user-auth.md](features/user-auth.md) |
| 用户自带 AI 配置(文本/图片/视频三类模型) | ✅ 做 → [ai-config.md](features/ai-config.md) |
| 结构化分析(角色/情节线/冲突/节奏) | ✅ 做(本期核心)→ [analysis.md](features/analysis.md) |
| 分镜编辑 / 逐镜视频 / 合并成片(视频生产流水线;**本期不含音频**) | ✅ 做 → [analysis.md](features/analysis.md) |
| 公共角色库(跨剧复用角色) | ✅ 做 → [character-library.md](features/character-library.md) |
| 任务中心 / 任务页(长任务状态:轮询 + WebSocket) | ✅ 做 → [analysis.md](features/analysis.md) §4.5 |
| 剧本生成(generation) | ⏸️ 推迟,保留愿景 |
| 多角色模拟(simulation) | ⏸️ 推迟,保留愿景 |

## 4. 功能索引

> 各功能点的需求条目、规则、页面、接口、专属待澄清,见 `features/` 下对应文档。

| 功能点 | 文档 | 编号 | 状态 |
|--------|------|------|------|
| 用户与认证 | [features/user-auth.md](features/user-auth.md) | FR-U | ✅ 本期 |
| AI 服务配置 | [features/ai-config.md](features/ai-config.md) | FR-C | ✅ 本期 |
| 结构化分析 | [features/analysis.md](features/analysis.md) | FR-A | ✅ 本期核心 |
| 公共角色库 | [features/character-library.md](features/character-library.md) | FR-L | ✅ 本期 |

**后续愿景(本期不做)**:

| 功能点 | 编号 | 状态 |
|--------|------|------|
| 剧本生成(generation) | FR-G1 | ⏸️ 推迟 |
| 多角色模拟(simulation) | FR-S1 | ⏸️ 推迟 |

## 5. 非功能需求

| 编号 | 维度 | 要求 |
|------|------|------|
| NFR-1 | 可复现性 | 后端可一条命令安装、运行、测试(工具链见 architecture §2) |
| NFR-2 | 供应商无关 | 模型访问供应商无关——切换供应商只改配置、不改代码(单一接缝见 architecture §4.2) |
| NFR-3 | 可维护性 | 统一 lint/format/类型检查,清晰模块边界(工具见 architecture §2) |
| NFR-4 | 类型安全 | 领域模型、配置、API 请求/响应具备静态类型校验(技术见 architecture §2) |
| NFR-5 | 可移植性 | macOS 优先;后端 Python、前端 Node(版本见 architecture §2) |
| NFR-6 | 认证与会话安全 | 用户名密码注册登录、签发 token;密码加盐哈希;令牌不得明文落盘/入日志,接口默认要求认证(具体方案见 [user-auth.md](features/user-auth.md)) |
| NFR-7 | 多租户隔离 | 所有数据访问强制带用户归属,杜绝越权读取他人数据 |
| NFR-8 | 凭证安全 | 用户 API Key 加密存储、脱敏展示,严禁明文落盘或进入日志(方案见 [ai-config.md](features/ai-config.md) §6) |

## 6. 未决问题(跨功能)

> 各功能点专属待澄清见其子文档;架构级未决项见 [`architecture/system-architecture.md`](../architecture/system-architecture.md) §6。此处仅列**跨功能(基础设施)**未定项。

1. **持久化配套**:ORM/迁移选型、是否需要长流程断点续跑(checkpointer)?候选见 architecture §6。

## 7. 范围边界(本期明确不做)

- 剧本生成(generation)与多角色模拟(simulation)的任何业务逻辑。
- 角色模拟相关的多 agent 编排。
- 用户间的协作/分享/评论(本期用户之间完全隔离)。
- 平台统一模型计费/代付(本期纯 BYOK,用户自带凭证)。
- 移动端原生 App(本期为 Web 应用)。

## 8. 与既有文档 / 变更的关系

- 本文档为总览;功能点细化见 [`features/`](features/)。
- 已与 [`architecture/system-architecture.md`](../architecture/system-architecture.md)(v0.4,前后端分离 Web 应用)对齐:多用户/认证落在 FastAPI 层,三类模型经 `core/llm` 接缝调用,分析实现为 LangGraph 分析图;**MySQL 持久化**已于 architecture v0.4 回写进技术栈表、目录结构与 §4.5。
- `openspec/changes/setup-project-foundation/` 的 proposal/design/specs/tasks 仍停留在**旧 CLI 单包**架构,与新需求、新架构均不一致,**需要同步修订或新建变更**(建议新建一个聚焦"用户体系 + 结构化分析"的变更,而非继续在 setup 变更上堆叠)。
