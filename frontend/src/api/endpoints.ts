import type {
  AccessTokenResponse,
  Analysis,
  AnalysisCurrentPatch,
  AnalysisSummary,
  CharacterCreate,
  CharacterUpdate,
  Drama,
  DramaCreate,
  Episode,
  EpisodeCharacter,
  EpisodeCreate,
  EpisodeUpdate,
  LoginRequest,
  ModelConfig,
  ModelConfigCreate,
  ModelConfigUpdate,
  ModelPurpose,
  RefreshRequest,
  RegisterRequest,
  Script,
  ScriptUpsert,
  ScriptVersion,
  Shot,
  ShotEditResult,
  ShotMerge,
  ShotPatch,
  ShotSplit,
  ShotsReorder,
  Task,
  TokenPairResponse,
  User,
} from '@/types'

import { request } from './client'

/**
 * 认证与当前用户端点(architecture.md §3.3 ①)。
 * 每个方法对齐一个 REST 路径;返回类型取自 `@/types`(与后端 pydantic 契约对齐)。
 *
 * 公开端点(register/login/refresh)一律 `skipAuthRefresh: true`:其 401 是"凭证
 * 错误"而非"access 过期",不可触发自动刷新(否则会把"密码错误"误判为需刷新)。
 */
export const authApi = {
  /** 注册:校验用户名/密码、argon2id 落库、签发 access + refresh,201。 */
  register(body: RegisterRequest): Promise<TokenPairResponse> {
    return request<TokenPairResponse>('/api/auth/register', {
      method: 'POST',
      body,
      skipAuthRefresh: true,
    })
  },

  /** 登录:校验密码、防爆破计数、成功签发 access + refresh。 */
  login(body: LoginRequest): Promise<TokenPairResponse> {
    return request<TokenPairResponse>('/api/auth/login', {
      method: 'POST',
      body,
      skipAuthRefresh: true,
    })
  },

  /** 刷新:凭 refresh 换新 access(spec:仅返回新 access;令牌轮换为可选增强)。 */
  refresh(body: RefreshRequest): Promise<AccessTokenResponse> {
    return request<AccessTokenResponse>('/api/auth/refresh', {
      method: 'POST',
      body,
      skipAuthRefresh: true,
    })
  },

  /** 登出:吊销当前 refresh(Bearer 鉴权 + body 指定要吊销的 refresh)。 */
  async logout(body: RefreshRequest): Promise<void> {
    await request<unknown>('/api/auth/logout', { method: 'POST', body })
  },

  /** 当前用户信息 + 文本模型配置完成度(GET /api/me)。 */
  getMe(): Promise<User> {
    return request<User>('/api/me')
  },
}

/**
 * BYOK 模型配置端点(architecture.md §3.3,setup-byok-config)。
 * 对齐 `/api/me/models/...`;响应仅脱敏 key(`api_key_masked`),明文 key 只在
 * create / update 请求体中,经 `request` 走标准 401 自动刷新拦截。
 */
export const modelsApi = {
  /** 列出我的模型配置(仅脱敏 key);`purpose` 可选过滤。 */
  list(purpose?: ModelPurpose): Promise<ModelConfig[]> {
    return request<ModelConfig[]>('/api/me/models', { query: { purpose } })
  },

  /** 获取单条配置(越权访问 → 404,不泄露存在性)。 */
  get(id: number): Promise<ModelConfig> {
    return request<ModelConfig>(`/api/me/models/${id}`)
  },

  /** 新建:白名单校验 → 信封加密落库 → 首条自动 active,201。 */
  create(body: ModelConfigCreate): Promise<ModelConfig> {
    return request<ModelConfig>('/api/me/models', { method: 'POST', body })
  },

  /** 按 model_fields_set 语义更新(仅传显式字段;缺省 key 不动加密列 D8)。 */
  update(id: number, body: ModelConfigUpdate): Promise<ModelConfig> {
    return request<ModelConfig>(`/api/me/models/${id}`, { method: 'PUT', body })
  },

  /** 删除;删 active 且同 purpose 有兄弟须指定继任 `newActiveId`,否则 409 invalid_state。 */
  async delete(id: number, newActiveId?: number): Promise<void> {
    await request<unknown>(`/api/me/models/${id}`, {
      method: 'DELETE',
      query: { new_active_id: newActiveId },
    })
  },

  /** 激活:单事务内翻转为当前 purpose 的 active(其余翻 0,D3)。 */
  activate(id: number): Promise<ModelConfig> {
    return request<ModelConfig>(`/api/me/models/${id}/activate`, { method: 'POST' })
  },

  /** 零成本自检(GET /models,不真生成);鉴权失败(401/403)置 invalid + 502。 */
  test(id: number): Promise<ModelConfig> {
    return request<ModelConfig>(`/api/me/models/${id}/test`, { method: 'POST' })
  },
}

/**
 * 剧目端点(architecture.md §3.3 ④;setup-structured-analysis §10.2)。
 * 越权 / 不存在 / 已删 → 404 not_found(不泄露存在性)。创建 201、软删 204。
 */
export const dramasApi = {
  /** 列出我的剧目(按 sort_order)。 */
  list(): Promise<Drama[]> {
    return request<Drama[]>('/api/dramas')
  },

  /** 新建剧目,201。 */
  create(body: DramaCreate): Promise<Drama> {
    return request<Drama>('/api/dramas', { method: 'POST', body })
  },

  /** 取剧目详情(越权 → 404)。 */
  get(dramaId: number): Promise<Drama> {
    return request<Drama>(`/api/dramas/${dramaId}`)
  },

  /** 重命名剧目(PUT)。 */
  rename(dramaId: number, body: DramaCreate): Promise<Drama> {
    return request<Drama>(`/api/dramas/${dramaId}`, { method: 'PUT', body })
  },

  /** 软删剧目(级联软删剧集),204。 */
  async remove(dramaId: number): Promise<void> {
    await request<unknown>(`/api/dramas/${dramaId}`, { method: 'DELETE' })
  },

  /** 列出剧目下的剧集。 */
  listEpisodes(dramaId: number): Promise<Episode[]> {
    return request<Episode[]>(`/api/dramas/${dramaId}/episodes`)
  },

  /** 新建剧集(设画幅 / 风格),201。 */
  createEpisode(dramaId: number, body: EpisodeCreate): Promise<Episode> {
    return request<Episode>(`/api/dramas/${dramaId}/episodes`, { method: 'POST', body })
  },
}

/**
 * 剧集端点(§10.3):剧集 CRUD + 剧本版本(append-only)+ AI 优化(异步 202)。
 * `select`(=accept=revert)移 current 指针、`reject` 显式 no-op(D6);版本保留。
 */
export const episodesApi = {
  /** 取剧集详情(越权 → 404)。 */
  get(episodeId: number): Promise<Episode> {
    return request<Episode>(`/api/episodes/${episodeId}`)
  },

  /** 更新剧集(仅传字段生效,null 清空 style_preset)。 */
  update(episodeId: number, body: EpisodeUpdate): Promise<Episode> {
    return request<Episode>(`/api/episodes/${episodeId}`, { method: 'PUT', body })
  },

  /** 删除剧集(软删),204。 */
  async remove(episodeId: number): Promise<void> {
    await request<unknown>(`/api/episodes/${episodeId}`, { method: 'DELETE' })
  },

  /** 写入剧本正文:产 source='input' 新版本并移 current 指针,返回该版本。 */
  upsertScript(episodeId: number, body: ScriptUpsert): Promise<ScriptVersion> {
    return request<ScriptVersion>(`/api/episodes/${episodeId}/script`, { method: 'PUT', body })
  },

  /** 取剧本容器(含 current_version_id);无容器 → 404(前端视为「无剧本」)。 */
  getScript(episodeId: number): Promise<Script> {
    return request<Script>(`/api/episodes/${episodeId}/script`)
  },

  /** 列剧本全部版本(新 → 旧)。 */
  listScriptVersions(episodeId: number): Promise<ScriptVersion[]> {
    return request<ScriptVersion[]>(`/api/episodes/${episodeId}/script/versions`)
  },

  /** 发起 AI 优化(copy-edit,D12):异步任务,202 返回 task;轮询 succeeded 后读 output_refs。 */
  optimize(episodeId: number): Promise<Task> {
    return request<Task>(`/api/episodes/${episodeId}/script/optimize`, { method: 'POST' })
  },

  /** 采纳 / 回退到指定版本(移 current 指针),返回该版本。 */
  selectVersion(episodeId: number, versionId: number): Promise<ScriptVersion> {
    return request<ScriptVersion>(
      `/api/episodes/${episodeId}/script/versions/${versionId}/select`,
      { method: 'POST' },
    )
  },

  /** 拒绝版本(no-op,指针不动、版本保留),204。 */
  async rejectVersion(episodeId: number, versionId: number): Promise<void> {
    await request<unknown>(
      `/api/episodes/${episodeId}/script/versions/${versionId}/reject`,
      { method: 'POST' },
    )
  },

  /**
   * 查询剧集在途任务(按 type);无在途 → 200 data=null(正常态,非 404)。供切 tab / 刷新 /
   * 重进页面时恢复 optimize 轮询——替代 sessionStorage(后者会因标签关闭、清缓存等丢失)。
   */
  getInflightTask(
    episodeId: number,
    type: 'analyze' | 'optimize',
  ): Promise<Task | null> {
    return request<Task | null>(`/api/episodes/${episodeId}/tasks/inflight`, {
      query: { type },
    })
  },
}

/**
 * 剧集角色端点(§10.4):预置角色 CRUD(preset)。`analysis` 源角色由拆解产出、只读,
 * 不经此 API 改;`fromLibraryId` 引入本期不实现(M4)。
 */
export const charactersApi = {
  /** 列出剧集角色(preset + analysis 两源)。 */
  list(episodeId: number): Promise<EpisodeCharacter[]> {
    return request<EpisodeCharacter[]>(`/api/episodes/${episodeId}/characters`)
  },

  /** 新建预置角色,201。 */
  create(episodeId: number, body: CharacterCreate): Promise<EpisodeCharacter> {
    return request<EpisodeCharacter>(`/api/episodes/${episodeId}/characters`, {
      method: 'POST',
      body,
    })
  },

  /** 取单角色(越权 → 404)。 */
  get(episodeId: number, characterId: number): Promise<EpisodeCharacter> {
    return request<EpisodeCharacter>(`/api/episodes/${episodeId}/characters/${characterId}`)
  },

  /** 更新角色(仅传字段生效)。 */
  update(
    episodeId: number,
    characterId: number,
    body: CharacterUpdate,
  ): Promise<EpisodeCharacter> {
    return request<EpisodeCharacter>(
      `/api/episodes/${episodeId}/characters/${characterId}`,
      { method: 'PUT', body },
    )
  },

  /** 删除角色(物理删;shot_characters FK CASCADE 清理),204。 */
  async remove(episodeId: number, characterId: number): Promise<void> {
    await request<unknown>(`/api/episodes/${episodeId}/characters/${characterId}`, {
      method: 'DELETE',
    })
  },
}

/**
 * 分析端点(§10.5):结构化拆解(异步 202)+ 双语义读(D11)+ 切换 current。
 * 门禁:无 active 文本配置 → 409 model_not_configured;无剧本 → 422 script_required;
 * 已有在途 → 409 invalid_state(串行约束 D3)。
 */
export const analysisApi = {
  /** 发起结构化拆解:异步跑分析图 → 落库(角色 / 分镜 / 出场)+ 移 current 指针。202 + 轮询。 */
  analyze(episodeId: number): Promise<Task> {
    return request<Task>(`/api/episodes/${episodeId}/analyze`, { method: 'POST' })
  },

  /** 双语义读:current_analysis(上次结果)+ inflight_task(在途)+ stale_flag(剧本已改)。 */
  getSummary(episodeId: number): Promise<AnalysisSummary> {
    return request<AnalysisSummary>(`/api/episodes/${episodeId}/analysis`)
  },

  /** 列全部分析(新→旧;D11「切回历史分镜」picker 用)。 */
  listHistory(episodeId: number): Promise<Analysis[]> {
    return request<Analysis[]>(`/api/episodes/${episodeId}/analyses`)
  },

  /** 切换 current_analysis_id 到指定历史 analysis(D11;须属本剧集)。 */
  selectCurrent(episodeId: number, body: AnalysisCurrentPatch): Promise<Analysis> {
    return request<Analysis>(`/api/episodes/${episodeId}/analysis/current`, {
      method: 'PATCH',
      body,
    })
  },
}

/**
 * 分镜端点(§10.6):列表 / 重排(`/episodes/:id/shots`)+ 拆 / 合 / 改(`/shots/:id`)。
 * `target_duration` 越界(∉ 3–15s)软标注,不阻断(D5);patch/split/merge 结果带 warnings。
 * reorder 后端将 warnings 置 meta,前端忽略、按 shot.target_duration 客户端派生高亮。
 */
export const shotsApi = {
  /** 列出当前分析的分镜(含出场角色回填)。 */
  list(episodeId: number): Promise<Shot[]> {
    return request<Shot[]>(`/api/episodes/${episodeId}/shots`)
  },

  /** 重排分镜(ordered_ids 须恰好覆盖 current_analysis 全部镜);返回重排后的清单。 */
  reorder(episodeId: number, body: ShotsReorder): Promise<Shot[]> {
    return request<Shot[]>(`/api/episodes/${episodeId}/shots/reorder`, { method: 'POST', body })
  },

  /** 改分镜字段(含出场全量替换);返回操作后的镜 + 越界标注。 */
  patch(shotId: number, body: ShotPatch): Promise<ShotEditResult> {
    return request<ShotEditResult>(`/api/shots/${shotId}`, { method: 'PATCH', body })
  },

  /** 在某镜后插入新镜(description 必填)。 */
  split(shotId: number, body: ShotSplit): Promise<ShotEditResult> {
    return request<ShotEditResult>(`/api/shots/${shotId}/split`, { method: 'POST', body })
  },

  /** 合并相邻两镜(须同 analysis,否则 409 conflict)。 */
  merge(shotId: number, body: ShotMerge): Promise<ShotEditResult> {
    return request<ShotEditResult>(`/api/shots/${shotId}/merge`, { method: 'POST', body })
  },
}

/**
 * 任务端点(§10.7):单任务轮询 + 协作式取消。
 * cancel 为协作式:置取消请求,终态落库由执行器后台完成,响应 task 可能仍显在途——
 * 前端轮询 `get` 确认 canceled。已终态任务 cancel → 409 invalid_state。
 */
export const tasksApi = {
  /** 获取任务(越权 → 404)。 */
  get(taskId: number): Promise<Task> {
    return request<Task>(`/api/tasks/${taskId}`)
  },

  /** 取消在途(pending/running)任务;终态任务 → 409 invalid_state。 */
  cancel(taskId: number): Promise<Task> {
    return request<Task>(`/api/tasks/${taskId}/cancel`, { method: 'POST' })
  },
}
