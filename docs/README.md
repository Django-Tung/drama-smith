# drama-smith 文档

drama-smith 是一个综合性戏剧/剧本创作工具链。本目录收纳**项目级**文档(相对稳定的认知),区别于 `openspec/`(管变更流程的工件)。

## 目录结构

```
docs/
├── README.md                          # 本索引
├── requirements/
│   ├── system-requirements.md         # 系统需求(总览):愿景、范围、功能索引、非功能
│   └── features/                      # 功能点细化(各自自包含)
│       ├── user-auth.md               # 用户与认证(FR-U)
│       ├── ai-config.md               # AI 服务配置(FR-C)
│       ├── analysis.md                # 结构化分析与分镜视频流水线(FR-A,本期核心)
│       └── character-library.md       # 公共角色库(FR-L)
├── architecture/
│   └── system-architecture.md         # 架构设计:技术栈、模块结构、关键决策(为什么这么选)
└── tech-solution/                     # 技术方案(实施落地):具体怎么搭
    ├── README.md                      # 总纲:框架、分工、原则、路线、默认决策
    ├── architecture.md                # 架构详案:拓扑、通信契约、任务执行模型
    ├── database.md                    # 数据库设计:ER、表结构、索引、隔离、迁移
    ├── backend.md                     # 后端方案:FastAPI 分层、LangGraph、core/llm、加密
    └── frontend.md                    # 前端方案:React 工程、状态、WS/REST 客户端
```

## 文档分层约定(写文档准则)

**需求文档讲"要什么",架构文档讲"为什么这么选",技术方案讲"具体怎么实施"。** 技术实现/选型的**决策记录**(为什么选 A 不选 B)归 `architecture/`;落地到**工程结构、表结构、模块详案、通信契约**的,归 `tech-solution/`;`requirements/` 只描述系统对外承诺的**行为与约束**,不写具体实现,遇到时以"见 §X"指向对应文档。

| 文档 | 职责(写什么) | 不写什么 |
|------|--------------|----------|
| `requirements/system-requirements.md` | 项目级概要、范围、功能索引、**非功能需求(行为级)**、跨功能未决问题 | 具体工具/版本/库名 |
| `requirements/features/*.md` | 各功能点的需求条目、业务规则、页面、**接口契约**、**安全需求与策略**、专属待澄清 | 框架、算法、令牌格式、加密算法等实现 |
| `architecture/system-architecture.md` | 技术栈、模块/目录结构、**关键设计决策(选型理由)**、技术级待定 | 工程落地细节(表 DDL、组件实现) |
| `tech-solution/*.md` | **实施落地**:运行时架构与通信契约、数据库 ER/表/索引、前后端工程结构与模块实现 | 「为什么选 X」的决策(归 architecture);需求条目(归 requirements) |

> 判据:能问"用哪个库 / 什么算法 / 走什么协议"的,先在 `architecture/` 记决策;能问"表怎么建 / 模块怎么分 / 接口帧怎么定"的,在 `tech-solution/` 落实施。各文档头部的「定位」行即本约定的复述。

## 与 OpenSpec 的关系

| | `docs/` | `openspec/` |
|---|---|---|
| 用途 | 沉淀项目级、相对稳定的文档 | 管理变更流程(proposal/design/specs/tasks) |
| 何时更新 | 认知稳定后手动维护 | 每次变更自动生成、归档时同步 |
| 读者 | 所有协作者 | 当前变更的实施者 |

两者互补:`openspec/` 管"这次要改什么",`docs/` 管"项目当前长什么样"。

## 阅读顺序

1. [`requirements/system-requirements.md`](requirements/system-requirements.md)——了解要做什么
2. [`architecture/system-architecture.md`](architecture/system-architecture.md)——了解为什么这么选(技术决策)
3. [`tech-solution/README.md`](tech-solution/README.md)——了解具体怎么实施(总纲 + 四篇子文档)
4. `openspec/changes/`——了解当前变更(注:`setup-project-foundation` 仍为旧 CLI 单包架构,与新 web 架构不一致,待新建聚焦"用户体系 + 结构化分析"的变更取代,见 [system-requirements §8](requirements/system-requirements.md))
