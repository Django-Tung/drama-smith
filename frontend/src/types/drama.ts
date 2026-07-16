/**
 * M2 结构化分析域类型,对齐后端 `api/schemas.py` 的 Public 契约(dramas / episodes /
 * script / characters / analysis / shots / tasks)。字段 snake_case 对齐 pydantic;
 * 响应类型对应后端 `*Public`(`from_attributes`)视图,前端省去 Public 后缀
 * (同 `ModelConfig` 约定;响应字段窄化为 Literal 联合,与 ModelConfig.purpose 同策略)。
 *
 * 四维分析产物(`AnalysisResult`)由 LLM 产出、后端以 `list[dict]` / `dict` 落库;
 * 前端按已知字段强类型 + 索引签名兜底,容忍提示词演进带来的额外字段。
 */

/** 画幅(Episode.aspect_ratio;创建时校验,落库为 VARCHAR)。 */
export type AspectRatio = '16:9' | '9:16' | '1:1' | '4:3'

/** 剧本格式(ScriptVersion.format)。 */
export type ScriptFormat = 'plain' | 'markdown' | 'fountain'

/** 景别(Shot.shot_type)。 */
export type ShotType = 'wide' | 'medium' | 'close' | 'extreme_close'

/** 剧集状态(Episode.status;M2 主要落在 draft/analyzing/ready)。 */
export type EpisodeStatus = 'draft' | 'analyzing' | 'ready' | 'rendering' | 'done'

/** 任务类型(Task.type;analyze / optimize 见 M2,image = 角色形象图异步生成,见 character-media)。 */
export type TaskType = 'analyze' | 'optimize' | 'image'

/**
 * 任务状态(Task.status)。
 * 在途:pending / running;终态:succeeded / failed / canceled(用户取消)/ interrupted(重启恢复)。
 */
export type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'canceled' | 'interrupted'

/** 任务终态集合(前端轮询退出条件;对齐后端 `tasks/states.TERMINAL`)。 */
export const TASK_TERMINAL: readonly TaskStatus[] = [
  'succeeded',
  'failed',
  'canceled',
  'interrupted',
] as const

/** 剧目(GET / POST /api/dramas)。 */
export interface Drama {
  id: number
  name: string
  sort_order: number
  created_at: string
  updated_at: string
}

/** 剧集(GET / POST /api/dramas/:dramaId/episodes)。 */
export interface Episode {
  id: number
  drama_id: number
  title: string
  sort_order: number
  aspect_ratio: AspectRatio
  style_preset: string | null
  status: EpisodeStatus
  /** 当前生效分析指针(null = 未拆解,D11)。 */
  current_analysis_id: number | null
  created_at: string
  updated_at: string
}

/** 剧本容器(与剧集 1:1,持当前版本指针)。 */
export interface Script {
  id: number
  episode_id: number
  /** 当前生效版本指针(null = 无剧本)。 */
  current_version_id: number | null
}

/** 剧本版本(不可变追加;source ∈ input / optimize)。 */
export interface ScriptVersion {
  id: number
  script_id: number
  version_no: number
  content: string
  format: ScriptFormat
  source: 'input' | 'optimize'
  created_at: string
}

/** 剧集角色(preset 用户预置 / analysis 拆解产出 两源)。 */
export interface EpisodeCharacter {
  id: number
  episode_id: number
  name: string
  role_type: string | null
  persona: string | null
  motivation: string | null
  traits: string[] | null
  appearance_desc: string | null
  /** 当前形象图指针(null=无形象图;逻辑指针无 FK,见 character-media)。 */
  image_media_id: number | null
  source: 'preset' | 'analysis'
  sort_order: number
  created_at: string
  updated_at: string
}

// ---- 富媒体(character-media;本期角色形象图)----

/** 媒体来源(Media.source)。 */
export type MediaSource = 'upload' | 'generate'

/**
 * 富媒体对外视图(media 元数据 + 短期签名 URL;本期 `kind='image'` 形象图)。
 * `signed_url` 为后端签发的相对 URL,`<img src>` 直用(无 Authorization 头)。
 * 对齐后端 `api/schemas.py::MediaPublic`。
 */
export interface MediaPublic {
  media_id: number
  signed_url: string
  content_type: string | null
  width: number | null
  height: number | null
  source: MediaSource
  created_at: string
}

// ---- 四维分析产物(Analysis.result;LLM 产出,已知字段 + 索引兜底)----

/** 拆解产出的角色项。 */
export interface AnalysisCharacter {
  name: string
  role_type?: string | null
  persona?: string | null
  motivation?: string | null
  traits?: string[]
  appearance_desc?: string | null
  [key: string]: unknown
}

/** 情节线项。 */
export interface AnalysisPlotline {
  name: string
  type?: string | null
  [key: string]: unknown
}

/** 冲突项。 */
export interface AnalysisConflict {
  type?: string | null
  parties?: string | null
  [key: string]: unknown
}

/** 节奏(幕结构 / 高潮分布等;对象)。 */
export interface AnalysisPacing {
  structure?: string | null
  climax?: string | null
  [key: string]: unknown
}

/** 四维分析结果(Analysis.result)。 */
export interface AnalysisResult {
  characters: AnalysisCharacter[]
  plotlines: AnalysisPlotline[]
  conflicts: AnalysisConflict[]
  pacing: AnalysisPacing
  [key: string]: unknown
}

/** 分析产物(append-only;GET .../analysis 的 current_analysis)。 */
export interface Analysis {
  id: number
  episode_id: number
  status: string
  result: AnalysisResult | null
  config_snapshot: Record<string, unknown> | null
  script_version_id: number
  created_at: string
  updated_at: string
}

/** GET /episodes/:id/analysis 双语义读(D11:上次结果 + 在途任务 + 过期标记)。 */
export interface AnalysisSummary {
  current_analysis: Analysis | null
  inflight_task: Task | null
  stale_flag: boolean
}

/** 任务(GET /api/tasks/:id;轮询单任务进度 / 状态)。 */
export interface Task {
  id: number
  user_id: number
  episode_id: number | null
  type: TaskType
  status: TaskStatus
  progress: number
  stage: string | null
  trigger: string
  input_snapshot: Record<string, unknown> | null
  /** 成功产物引用(analyze → analysis_id;optimize → version_id + diff)。 */
  output_refs: Record<string, unknown> | null
  /** 失败原因体({ code, message })。 */
  error: Record<string, unknown> | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

/** 分镜出场角色引用(角色 id + 名 + 该镜内作用)。 */
export interface ShotAppearRef {
  episode_character_id: number
  name: string
  role_in_shot: string | null
}

/** 分镜(GET /episodes/:id/shots;appearing 由 API 层回填,非 ORM 列)。 */
export interface Shot {
  id: number
  analysis_id: number
  episode_id: number
  seq: number
  description: string
  shot_type: ShotType | null
  scene: string | null
  plot_point: string | null
  dialogue: string | null
  target_duration: number | null
  camera_move: string | null
  related_plotline: string | null
  related_conflict: string | null
  appearing: ShotAppearRef[]
}

/** `target_duration` 越界标注(D5,软校验不阻断保存)。 */
export interface ShotWarning {
  shot_id: number
  target_duration: number
  issue: 'too_short' | 'too_long'
}

/** patch / split / merge 结果(操作后的镜 + 越界标注)。 */
export interface ShotEditResult {
  shot: Shot
  warnings: ShotWarning[]
}

// ---- 请求体(对齐后端 `extra="forbid"`;未知键 422)----

/** 新建剧目 / 重命名(POST /api/dramas、PUT /api/dramas/:id)。 */
export interface DramaCreate {
  name: string
}

/** 更新剧集(PUT /api/episodes/:id;全可选,缺省不改、null 清空 style_preset)。 */
export interface EpisodeUpdate {
  title?: string
  aspect_ratio?: AspectRatio
  style_preset?: string | null
  status?: EpisodeStatus
}

/** 新建剧集(POST /api/dramas/:dramaId/episodes)。 */
export interface EpisodeCreate {
  title: string
  aspect_ratio: AspectRatio
  style_preset?: string | null
}

/** 写入剧本正文(PUT /api/episodes/:id/script;产 input 版本并移 current 指针)。 */
export interface ScriptUpsert {
  content: string
  format?: ScriptFormat
}

/** 新建预置角色(POST /api/episodes/:id/characters)。 */
export interface CharacterCreate {
  name: string
  role_type?: string | null
  persona?: string | null
  motivation?: string | null
  traits?: string[]
  appearance_desc?: string | null
  sort_order?: number
}

/** 更新角色(PUT /api/episodes/:id/characters/:cid;全可选)。 */
export interface CharacterUpdate {
  name?: string
  role_type?: string | null
  persona?: string | null
  motivation?: string | null
  traits?: string[]
  appearance_desc?: string | null
  sort_order?: number
}

/** 切换当前分析指针(PATCH /api/episodes/:id/analysis/current;D11)。 */
export interface AnalysisCurrentPatch {
  analysis_id: number
}

/** 改分镜字段(PATCH /api/shots/:id;appearing 给出则全量替换出场角色)。 */
export interface ShotPatch {
  description?: string
  shot_type?: ShotType
  scene?: string
  plot_point?: string
  dialogue?: string
  target_duration?: number
  camera_move?: string
  related_plotline?: string
  related_conflict?: string
  /** 给出则全量替换出场角色(episode_character_id 列表)。 */
  appearing?: number[]
}

/** 在某镜后插入新镜(POST /api/shots/:id/split;description 必填)。 */
export interface ShotSplit {
  description: string
  shot_type?: ShotType
  scene?: string
  plot_point?: string
  dialogue?: string
  target_duration?: number
  camera_move?: string
  related_plotline?: string
  related_conflict?: string
  appearing?: number[]
}

/** 合并相邻两镜(POST /api/shots/:id/merge;须同 analysis)。 */
export interface ShotMerge {
  into_shot_id: number
}

/** 重排分镜(POST /api/episodes/:id/shots/reorder;须恰好覆盖其全部镜 id)。 */
export interface ShotsReorder {
  ordered_ids: number[]
}
