/**
 * BYOK 模型配置域类型,对齐后端 `api/schemas.py` 的 `ModelConfig*` 契约与
 * `llm/base.py` 的供应商白名单(ai-config §2.1)。字段 snake_case 对齐 pydantic。
 *
 * key 字段在响应中仅以 `api_key_masked`(脱敏串)出现;明文 key 仅存在于
 * 创建 / 更新请求体,永不落本地、不出请求。
 */

/** 模型用途:text 为必配(前端门禁),image / video 可选。 */
export type ModelPurpose = 'text' | 'image' | 'video'

/** 配置运行态:active 正常;自检鉴权失败(401/403)置 invalid(FR-C5)。 */
export type ModelStatus = 'active' | 'invalid'

/** 文本供应商白名单(llm/base.py TEXT_PROVIDERS)。 */
export type TextProvider =
  | 'openai'
  | 'anthropic'
  | 'gemini'
  | 'zhipu'
  | 'deepseek'
  | 'moonshot'
  | 'qwen'
  | 'doubao'
  | 'xai'

/** 图片供应商白名单(llm/base.py IMAGE_PROVIDERS)。 */
export type ImageProvider =
  | 'openai'
  | 'seedream'
  | 'wanx'
  | 'cogview'
  | 'flux'
  | 'stability'
  | 'ideogram'

/** 视频供应商白名单(llm/base.py VIDEO_PROVIDERS;本期列但不实现,M3 落适配器)。 */
export type VideoProvider =
  | 'seedance'
  | 'kling'
  | 'veo'
  | 'wan'
  | 'minimax'
  | 'runway'
  | 'pika'
  | 'luma'
  | 'sora'

/** 所有 purpose 的供应商并集;`openai` 跨 text / image。 */
export type Provider = TextProvider | ImageProvider | VideoProvider

/** 已存模型配置(GET /api/me/models,仅脱敏 key)。 */
export interface ModelConfig {
  id: number
  purpose: ModelPurpose
  provider: Provider
  model: string
  base_url: string | null
  /** 脱敏 API Key(前 3 … 后 4);明文 key 永不在响应中出现。 */
  api_key_masked: string
  params: Record<string, unknown> | null
  provider_options: Record<string, unknown> | null
  /** 是否当前 purpose 的生效配置(每用户每用途恰一条 active)。 */
  is_active: boolean
  status: ModelStatus
  /** 最近一次零成本自检时间(ISO 8601)。 */
  last_tested_at: string | null
}

/** 创建模型配置请求(POST /api/me/models)。明文 api_key 仅本次加密,不入本地。 */
export interface ModelConfigCreate {
  purpose: ModelPurpose
  /** 须落在该 purpose 的供应商白名单内(后端 model_validator 复校 → 422)。 */
  provider: string
  model: string
  api_key: string
  base_url?: string | null
  params?: Record<string, unknown> | null
  provider_options?: Record<string, unknown> | null
}

/** 更新模型配置请求(PUT /api/me/models/:id)。purpose 不可改;字段缺省即不动。 */
export interface ModelConfigUpdate {
  provider?: string
  model?: string
  /** 键出现且 null → 显式清空;键不出现 → 不动。 */
  base_url?: string | null
  /** 给出则全量重封;缺省 / null 不动加密列(D8)。 */
  api_key?: string
  params?: Record<string, unknown> | null
  provider_options?: Record<string, unknown> | null
}
