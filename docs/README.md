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
│       └── analysis.md                # 结构化分析(FR-A,本期核心)
└── architecture/
    └── system-architecture.md         # 架构设计:技术栈、模块结构、关键决策
```

## 文档分层约定(写文档准则)

**需求文档讲"要什么",架构文档讲"怎么实现"。** 技术实现/选型(框架、库、算法、存储引擎、协议、编排引擎、目录结构)只进 `architecture/`;`requirements/` 不写具体实现,遇到时以"见 architecture §X"指向。

| 文档 | 职责(写什么) | 不写什么 |
|------|--------------|----------|
| `requirements/system-requirements.md` | 项目级概要、范围、功能索引、**非功能需求(行为级)**、跨功能未决问题 | 具体工具/版本/库名 |
| `requirements/features/*.md` | 各功能点的需求条目、业务规则、页面、**接口契约**、**安全需求与策略**、专属待澄清 | 框架、算法、令牌格式、加密算法等实现 |
| `architecture/system-architecture.md` | 技术栈、模块/目录结构、关键设计决策、实现选型、技术级待定 | — |

> 判据:凡能问"用哪个库 / 什么算法 / 走什么协议"的,都属于架构;需求只描述系统对外承诺的**行为与约束**。各文档头部的「定位」行即本约定的复述。

## 与 OpenSpec 的关系

| | `docs/` | `openspec/` |
|---|---|---|
| 用途 | 沉淀项目级、相对稳定的文档 | 管理变更流程(proposal/design/specs/tasks) |
| 何时更新 | 认知稳定后手动维护 | 每次变更自动生成、归档时同步 |
| 读者 | 所有协作者 | 当前变更的实施者 |

两者互补:`openspec/` 管"这次要改什么",`docs/` 管"项目当前长什么样"。

## 阅读顺序

1. [`requirements/system-requirements.md`](requirements/system-requirements.md)——了解要做什么
2. [`architecture/system-architecture.md`](architecture/system-architecture.md)——了解怎么做
3. `openspec/changes/`——了解当前变更(注:`setup-project-foundation` 仍为旧 CLI 单包架构,与新 web 架构不一致,待新建聚焦"用户体系 + 结构化分析"的变更取代,见 [system-requirements §8](requirements/system-requirements.md))
