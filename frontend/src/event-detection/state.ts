import type { EventSourceRead, MotionSensitivity, MotionSourceDraft } from './types'

const motionDraftKeys: (keyof MotionSourceDraft)[] = [
  'enabled',
  'sensitivity',
  'analysis_fps',
  'analysis_width',
  'min_duration_ms',
  'merge_gap_ms',
  'event_min_interval_ms',
]

function firstQueryValue(value: unknown): unknown {
  return Array.isArray(value) ? value[0] : value
}

export function cameraIdFromDetectionQuery(value: unknown): number | null {
  const raw = firstQueryValue(value)
  if (typeof raw !== 'string' && typeof raw !== 'number') return null
  const parsed = Number(raw)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function numericConfig(config: Record<string, unknown>, key: string, fallback: number): number {
  const value = Number(config[key])
  return Number.isFinite(value) ? value : fallback
}

function sensitivityConfig(config: Record<string, unknown>): MotionSensitivity {
  const value = config.sensitivity
  return value === 'low' || value === 'high' ? value : 'medium'
}

export function motionDraftFromSource(source: EventSourceRead): MotionSourceDraft {
  const config = source.config
  return {
    enabled: config.enabled === true,
    sensitivity: sensitivityConfig(config),
    analysis_fps: numericConfig(config, 'analysis_fps', 5),
    analysis_width: numericConfig(config, 'analysis_width', 640),
    min_duration_ms: numericConfig(config, 'min_duration_ms', 800),
    merge_gap_ms: numericConfig(config, 'merge_gap_ms', 10_000),
    event_min_interval_ms: numericConfig(config, 'event_min_interval_ms', 60_000),
  }
}

export function countMotionDraftChanges(
  saved: MotionSourceDraft | null | undefined,
  draft: MotionSourceDraft | null | undefined,
): number {
  if (!saved || !draft) return 0
  return motionDraftKeys.reduce((count, key) => count + (saved[key] === draft[key] ? 0 : 1), 0)
}

export function serializeMotionSourcePayload(draft: MotionSourceDraft): MotionSourceDraft {
  return {
    enabled: draft.enabled,
    sensitivity: draft.sensitivity,
    analysis_fps: draft.analysis_fps,
    analysis_width: draft.analysis_width,
    min_duration_ms: draft.min_duration_ms,
    merge_gap_ms: draft.merge_gap_ms,
    event_min_interval_ms: draft.event_min_interval_ms,
  }
}
