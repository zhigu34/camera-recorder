export const PLAYBACK_RATES = [0.5, 1, 1.5, 2, 4] as const
export const SKIP_INTERVALS = [5, 10, 15, 20, 25, 30] as const
export const DEFAULT_PLAYBACK_RATE = 1
export const DEFAULT_SKIP_INTERVAL = 10
export const SKIP_INTERVAL_STORAGE_KEY = 'camera-recorder.playback-skip-seconds'

export function normalizePlaybackRate(value: unknown) {
  const parsed = Number(value)
  return PLAYBACK_RATES.includes(parsed as (typeof PLAYBACK_RATES)[number])
    ? parsed
    : DEFAULT_PLAYBACK_RATE
}

export function normalizeSkipInterval(value: unknown) {
  const parsed = Number(value)
  return SKIP_INTERVALS.includes(parsed as (typeof SKIP_INTERVALS)[number])
    ? parsed
    : DEFAULT_SKIP_INTERVAL
}

export function loadSkipInterval(storage?: Pick<Storage, 'getItem'> | null) {
  if (!storage) return DEFAULT_SKIP_INTERVAL
  try {
    return normalizeSkipInterval(storage.getItem(SKIP_INTERVAL_STORAGE_KEY))
  } catch {
    return DEFAULT_SKIP_INTERVAL
  }
}

export function saveSkipInterval(value: unknown, storage?: Pick<Storage, 'setItem'> | null) {
  const normalized = normalizeSkipInterval(value)
  if (!storage) return normalized
  try {
    storage.setItem(SKIP_INTERVAL_STORAGE_KEY, String(normalized))
  } catch {
    // Playback controls remain usable when storage is unavailable.
  }
  return normalized
}

export function playbackSkipTarget(
  activeWallSeconds: number | null,
  deltaSeconds: number,
) {
  if (activeWallSeconds === null || !Number.isFinite(activeWallSeconds)) return null
  const delta = Number.isFinite(deltaSeconds) ? deltaSeconds : 0
  return Math.max(0, Math.min(86400, activeWallSeconds + delta))
}
