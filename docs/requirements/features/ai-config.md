# AI 服务配置(FR-C)

> 所属:drama-smith 需求 · 功能点细化 · v0.3 · 2026-06-26
> 父文档:[system-requirements.md](../system-requirements.md)
> 关联编号:FR-C · 切面:用户配置

## 1. 概述

每个用户**自带模型凭证(BYOK)**,不依赖平台统一密钥。**首次登录强制配置文本模型**(图片/视频可选):未配置图片/视频时,相应的图像增强(FR-A3)与分镜动态预览(FR-A4)不可用,但**不阻塞进入主功能**。文本拆解始终可用;三类模型的实际调用见 [`analysis.md`](./analysis.md)。

## 2. 配置槽位定义

每个模型配置包含:

- **用途**:text / image / video(固定三类)
- **供应商** provider(取自 §2.1 白名单)
- **模型标识** model
- **API Key**(加密存储、不明文回显)
- 可选 **base_url / 代理**(兼容自部署 / 第三方网关)
- 可选**调用参数**(按模型类型给默认值:文本 `temperature`/`max_tokens`;图片 `size`/`quality`/`n`;视频 `duration`/`resolution`/`aspect`)
- **供应商扩展字段**(按需):少数供应商不止一个 key——如 Azure OpenAI 还需 `endpoint`/`api_version`/`deployment`。预留开放的 `provider_options` 字段承接。

### 2.1 供应商白名单(首发)

> 首发支持的供应商清单(接入经统一模型接缝,具体接入实现见 [`architecture`](../../architecture/system-architecture.md) §4.2)。**第三方网关 / 自部署**以"OpenAI 兼容 + base_url"形态接入(one-api / new-api / OpenRouter / SiliconFlow 硅基流动 / vLLM / Ollama 等)。

| 用途 | 供应商(代表模型) | 接入形态 |
|------|------------------|----------|
| 文本 text | OpenAI(GPT)、Anthropic(Claude)、Google(Gemini)、智谱(GLM)、DeepSeek、Moonshot Kimi、通义千问 Qwen、豆包 Doubao、xAI Grok | 原生 / OpenAI 兼容 |
| 图片 image | OpenAI(gpt-image-1)、字节即梦 Seedream、通义万相、智谱 CogView、Black Forest Labs FLUX、Stability、Ideogram | 原生 / 网关(Replicate·SiliconFlow·fal)/ OpenAI 兼容 |
| 视频 video | 字节即梦 Seedance、快手可灵 Kling、Google Veo、通义万相 Wan、Minimax 海螺、Runway·Pika·Luma、OpenAI Sora | 多为异步、协议差异大,需自定义适配(见 architecture §4.2) |

> 视频类供应商协议差异大、多为异步,接入需特殊处理(见 [`architecture`](../../architecture/system-architecture.md) §4.2);NFR-2「供应商无关、切换只改配置」仍为硬约束。

### 2.2 每类用途的模型数量

**每类用途允许配置多个模型,其中之一为"当前生效"(默认),可一键切换。**

- 一个用途 = 0..N 条配置;**有配置时**,任意时刻恰有一条标记为 active(0 条则该用途不可用)。
- 切换默认 = 仅置位 `active` 标记,不动 key/参数(满足 NFR-2:切换只改配置)。
- 首次配置向导中,每类配齐的第一条自动设为 active。
- 删除 active 项时:若该类仍有其他配置,要求先指定新 active;**文本类**删除最后一条会重新触发 FR-C1(强制补配);**图片/视频类**删除最后一条仅禁用相应功能,不阻塞主功能。

## 3. 需求条目

| 编号 | 需求 | 说明 |
|------|------|------|
| FR-C1 | 首次登录强制配置文本 | 新用户首次登录**必须配置文本模型**方可进入主功能;图片/视频可选,未配置则禁用 FR-A3/A4(详见 §2.2、[`analysis.md`](./analysis.md)) |
| FR-C2 | 配置增删改 + 默认切换 | 增删改 + 为每类用途在多条配置间指定/切换当前生效模型(§2.2) |
| FR-C3 | 连通性自检 | 保存前一键测试鉴权与通路,**不产生真实生成费用、不真生成图/视频**(本配置模块职责仅限连通性,生成在 analysis 子系统);个别供应商无法零成本探测时降级或跳过 |
| FR-C4 | 凭证安全 | API Key 加密存储;列表/日志脱敏,严禁明文回显或落盘(方案见 §6) |
| FR-C5 | 凭证失效检测 | 运行期遇 401/403/鉴权失败,标记该配置失效并提示重新配置,按 §2.2 回退或阻断该用途 |
| FR-C6 | 超时 / 重试 / 限流 | 每类用途给默认超时与有限重试;429/超时按用途降级或重试,参数落于 §2 `provider_options` / 系统默认(具体值随变更定) |

## 4. 页面

- **首次配置向导**:仅在**文本模型未配置**时出现;必配文本(自检通过方可继续),图片/视频为可选步骤、可跳过。
- **设置页**:模型配置增删改、为每类用途指定当前生效模型。

## 5. 接口(草案;字段契约随变更定)

| 资源 | 端点示例 | 说明 |
|------|----------|------|
| 模型配置 | `GET/POST/PUT/DELETE /api/me/models` | 三类模型配置 CRUD |
| 切换默认 | `POST /api/me/models/:id/activate` | 将该配置置为其用途的当前生效模型 |
| 连通性自检 | `POST /api/me/models/:id/test` | 测试单条配置可达 |

## 6. 安全要求

- API Key 加密存储、脱敏展示,严禁明文落盘或进入日志(NFR-8;加密方案见 [`architecture`](../../architecture/system-architecture.md) §4.5)。
- 模型访问经统一接缝,供应商无关(NFR-2;见 architecture §4.2)。

## 7. 决策记录

> 本节原 5 项待澄清已于 2026-06-25 全部裁定,落点如下;无遗留待定。

1. **首次配置严格度** → **文本必配,图片/视频可选**:未配置则禁用 FR-A3/A4,不阻塞进入主功能(已写入 FR-C1、§1、§4)。
2. **视频供应商接入** → **允许经统一接缝补自定义适配器**,不限定供应商范围(见 §2.1、architecture §4.2)。
3. **自检计费策略** → **配置模块不生成图/视频**:自检仅做零成本鉴权探测、无费用,原问题忽略(已写入 FR-C3)。
4. **配置与在途任务并发** → **沿用任务发起时的快照**,运行中改配置不影响在途调用。
5. **provider 扩展字段** → **预留** `provider_options`,具体字段集实现时定(§2)。
