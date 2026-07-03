import type { ModelPurpose } from '@/types'

/**
 * BYOK 供应商目录(对齐后端 `llm/base.py` 白名单,取自 ai-config §2.1)。
 * `PROVIDERS` 顺序即下拉顺序;`DEFAULT_MODELS` 为选供应商时的便捷预填(可改);
 * 视频首发「列但不实现」(M3 落异步适配器),故不给默认模型。
 */

/** 供应商中文标签(缺失回退原 id)。 */
const LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  gemini: 'Gemini',
  zhipu: '智谱 GLM',
  deepseek: 'DeepSeek',
  moonshot: 'Moonshot',
  qwen: '通义千问',
  doubao: '豆包',
  xai: 'xAI',
  seedream: 'Seedream',
  wanx: '万象 WanX',
  cogview: 'CogView',
  flux: 'FLUX',
  stability: 'Stability',
  ideogram: 'Ideogram',
  seedance: 'Seedance',
  kling: '可灵 Kling',
  veo: 'Veo',
  wan: 'Wan',
  minimax: 'MiniMax',
  runway: 'Runway',
  pika: 'Pika',
  luma: 'Luma',
  sora: 'Sora',
}

/** 各 purpose 的供应商选项(取自 llm/base.py 的 TEXT/IMAGE/VIDEO_PROVIDERS)。 */
export const PROVIDERS: Record<ModelPurpose, readonly string[]> = {
  text: ['openai', 'anthropic', 'gemini', 'zhipu', 'deepseek', 'moonshot', 'qwen', 'doubao', 'xai'],
  image: ['openai', 'seedream', 'wanx', 'cogview', 'flux', 'stability', 'ideogram'],
  video: ['seedance', 'kling', 'veo', 'wan', 'minimax', 'runway', 'pika', 'luma', 'sora'],
}

/** 各 (purpose, provider) 的默认模型标识;选供应商时自动填入(用户可覆盖)。 */
const DEFAULT_MODELS: Record<string, string> = {
  'text:openai': 'gpt-4o-mini',
  'text:anthropic': 'claude-3-5-sonnet-latest',
  'text:gemini': 'gemini-1.5-flash',
  'text:zhipu': 'glm-4-flash',
  'text:deepseek': 'deepseek-chat',
  'text:moonshot': 'moonshot-v1-8k',
  'text:qwen': 'qwen-turbo',
  'text:doubao': 'doubao-pro-32k',
  'text:xai': 'grok-2',
  'image:openai': 'dall-e-3',
  'image:seedream': 'seedream-3-0',
  'image:wanx': 'wanx-v1',
  'image:cogview': 'cogview-3-plus',
  'image:flux': 'flux-pro-1.1',
  'image:stability': 'stable-image-core',
  'image:ideogram': 'ideogram-v2',
}

/** 供应商显示名。 */
export function providerLabel(id: string): string {
  return LABELS[id] ?? id
}

/** 选供应商时的默认模型;无则空串(视频 M3 待定)。 */
export function defaultModel(purpose: ModelPurpose, provider: string): string {
  return DEFAULT_MODELS[`${purpose}:${provider}`] ?? ''
}

/** 校验 (purpose, provider) 是否在白名单内(对齐后端 model_validator → 422)。 */
export function isWhitelisted(purpose: ModelPurpose, provider: string): boolean {
  return PROVIDERS[purpose].includes(provider)
}
