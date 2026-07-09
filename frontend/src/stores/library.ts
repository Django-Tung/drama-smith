import { create } from 'zustand'

import { dramasApi, episodesApi } from '@/api/endpoints'
import { ApiError } from '@/api/errors'
import type { AspectRatio, Drama, Episode } from '@/types'

/**
 * 列表载入三态(D10:`idle` → `loading` → `ready` | `error`)。
 * `idle` 仅初次未拉取;`loading` 用于占位;`ready`/`error` 区分成败。
 */
type ListStatus = 'idle' | 'loading' | 'ready' | 'error'

/** 把异常收敛为可展示文案(ApiError 取后端 message,否则用兜底)。 */
function msg(e: unknown, fallback: string): string {
  return ApiError.isApiError(e) ? e.message : fallback
}

interface LibraryState {
  /** 我的剧目(按 sort_order)。 */
  dramas: Drama[]
  dramasStatus: ListStatus
  dramasError: string | null
  /** 当前展开的剧(null = 未选,仅显示剧目列表)。 */
  selectedDramaId: number | null
  /** `selectedDramaId` 名下剧集。 */
  episodes: Episode[]
  episodesStatus: ListStatus
  episodesError: string | null

  loadDramas: () => Promise<void>
  /** 展开某剧并载其剧集;传 null 收起。 */
  selectDrama: (id: number | null) => Promise<void>
  createDrama: (name: string) => Promise<Drama>
  renameDrama: (id: number, name: string) => Promise<void>
  /** 软删剧(级联软删剧集);删中的是当前剧则一并收起。 */
  deleteDrama: (id: number) => Promise<void>
  createEpisode: (
    dramaId: number,
    input: { title: string; aspect_ratio: AspectRatio; style_preset?: string | null },
  ) => Promise<Episode>
  renameEpisode: (id: number, title: string) => Promise<void>
  /** 软删剧集。 */
  deleteEpisode: (id: number) => Promise<void>
}

/**
 * 剧库浏览级状态(D10:Zustand + 手动 `request`,不引 TanStack Query)。
 * 只持「我的剧目 + 选中剧的剧集」两级浏览数据;剧集工作台 / 分镜台是 per-episode
 * 工作面,用本地态(见 `features/episode`、`features/shots`)。写操作做**就地增量**
 * 更新(append / map / filter),避免整树重载闪烁;失败抛出,由调用方捕获做 UI 反馈。
 */
export const useLibraryStore = create<LibraryState>((set, get) => ({
  dramas: [],
  dramasStatus: 'idle',
  dramasError: null,
  selectedDramaId: null,
  episodes: [],
  episodesStatus: 'idle',
  episodesError: null,

  async loadDramas() {
    set({ dramasStatus: 'loading', dramasError: null })
    try {
      const dramas = await dramasApi.list()
      set({ dramas, dramasStatus: 'ready' })
    } catch (e) {
      set({ dramasStatus: 'error', dramasError: msg(e, '加载剧目失败') })
    }
  },

  async selectDrama(id) {
    set({
      selectedDramaId: id,
      episodes: [],
      episodesStatus: id == null ? 'idle' : 'loading',
      episodesError: null,
    })
    if (id == null) return
    try {
      const episodes = await dramasApi.listEpisodes(id)
      // 防竞:用户可能在请求在途时又切到别的剧,丢弃陈旧结果。
      if (get().selectedDramaId !== id) return
      set({ episodes, episodesStatus: 'ready' })
    } catch (e) {
      if (get().selectedDramaId !== id) return
      set({ episodesStatus: 'error', episodesError: msg(e, '加载剧集失败') })
    }
  },

  async createDrama(name) {
    const drama = await dramasApi.create({ name })
    // 新剧 sort_order 最大 → 追加到末尾即正确序。
    set((s) => ({ dramas: [...s.dramas, drama] }))
    return drama
  },

  async renameDrama(id, name) {
    const drama = await dramasApi.rename(id, { name })
    set((s) => ({ dramas: s.dramas.map((d) => (d.id === id ? drama : d)) }))
  },

  async deleteDrama(id) {
    await dramasApi.remove(id)
    set((s) => {
      const wasSelected = s.selectedDramaId === id
      return {
        dramas: s.dramas.filter((d) => d.id !== id),
        selectedDramaId: wasSelected ? null : s.selectedDramaId,
        episodes: wasSelected ? [] : s.episodes,
        episodesStatus: wasSelected ? 'idle' : s.episodesStatus,
      }
    })
  },

  async createEpisode(dramaId, input) {
    const ep = await dramasApi.createEpisode(dramaId, input)
    // 仅当该剧正展开时追加(用户可能在请求在途时收起)。
    set((s) => (s.selectedDramaId === dramaId ? { episodes: [...s.episodes, ep] } : {}))
    return ep
  },

  async renameEpisode(id, title) {
    const ep = await episodesApi.update(id, { title })
    set((s) => ({ episodes: s.episodes.map((e) => (e.id === id ? ep : e)) }))
  },

  async deleteEpisode(id) {
    await episodesApi.remove(id)
    set((s) => ({ episodes: s.episodes.filter((e) => e.id !== id) }))
  },
}))
