/** 分镜 `target_duration` 合理区间(D5:3–15s,软校验不阻断)。 */
export const DURATION_MIN = 3
export const DURATION_MAX = 15

/** ISO → 本地化日期时间(沿用 M1 `new Date(iso).toLocaleString()` 范式,抽公共)。 */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString()
}

/** `target_duration` 是否越界(D5);null / undefined 视为无值、不算越界。 */
export function isDurationOutOfRange(d: number | null | undefined): boolean {
  return d != null && (d < DURATION_MIN || d > DURATION_MAX)
}

/** 越界方向(`too_short` / `too_long`);未越界或无值返回 null。 */
export function durationIssue(d: number | null | undefined): 'too_short' | 'too_long' | null {
  if (d == null) return null
  if (d < DURATION_MIN) return 'too_short'
  if (d > DURATION_MAX) return 'too_long'
  return null
}
