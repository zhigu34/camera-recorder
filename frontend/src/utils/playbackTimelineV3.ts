export const ZOOM_SPANS = {
  '24h': 24 * 60 * 60,
  '6h': 6 * 60 * 60,
  '1h': 60 * 60,
  '15m': 15 * 60,
} as const

export type PlaybackZoom = keyof typeof ZOOM_SPANS

export interface TimelineRange {
  left: number
  width: number
}

export interface TimelineRecording {
  id: number
  started_at?: string | null
  ended_at?: string | null
  duration?: number | null
}

function round4(value: number) {
  return Math.round(value * 10_000) / 10_000
}

export function wallClockSeconds(value?: string | null) {
  if (!value) return null
  const match = value.match(/T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?/)
  if (!match) return null
  const fraction = match[4] ? Number(`0.${match[4]}`) : 0
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]) + fraction
}

export function clampViewport(start: number, span: number) {
  const safeSpan = Math.max(1, Math.min(86400, span))
  return Math.max(0, Math.min(86400 - safeSpan, start))
}

export function timeAtPointer(viewStart: number, viewSpan: number, pointerRatio: number) {
  const ratio = Math.max(0, Math.min(1, pointerRatio))
  return Math.max(0, Math.min(86400, viewStart + viewSpan * ratio))
}

export function rangePercent(start: number, end: number, viewStart: number, viewSpan: number): TimelineRange | null {
  if (!Number.isFinite(start) || !Number.isFinite(end) || !Number.isFinite(viewStart) || !Number.isFinite(viewSpan) || viewSpan <= 0 || end <= start) return null
  const viewEnd = viewStart + viewSpan
  if (end <= viewStart || start >= viewEnd) return null
  const clippedStart = Math.max(start, viewStart)
  const clippedEnd = Math.min(end, viewEnd)
  return {
    left: round4(((clippedStart - viewStart) / viewSpan) * 100),
    width: round4(((clippedEnd - clippedStart) / viewSpan) * 100),
  }
}

export function zoomAround(viewStart: number, currentSpan: number, nextSpan: number, anchorRatio: number) {
  const ratio = Math.max(0, Math.min(1, anchorRatio))
  const anchorTime = timeAtPointer(viewStart, currentSpan, ratio)
  return clampViewport(anchorTime - nextSpan * ratio, nextSpan)
}

export function recordingRange(item: TimelineRecording) {
  const start = wallClockSeconds(item.started_at)
  if (start === null) return null
  const explicitEnd = wallClockSeconds(item.ended_at)
  const duration = Math.max(0, Number(item.duration || 0))
  const end = Math.max(start, Math.min(86400, explicitEnd ?? start + duration))
  return end > start ? { start, end } : null
}

export function findRecordingAtWallTime<T extends TimelineRecording>(recordings: T[], wallSeconds: number): T | null {
  const target = Math.max(0, Math.min(86400, wallSeconds))
  for (const recording of recordings) {
    const range = recordingRange(recording)
    if (range && target >= range.start && target < range.end) return recording
  }
  return null
}

export function recordingSeekOffset(recording: TimelineRecording, wallSeconds: number) {
  const start = wallClockSeconds(recording.started_at)
  if (start === null) return 0
  const duration = Math.max(0, Number(recording.duration || 0))
  return Math.max(0, Math.min(duration, wallSeconds - start))
}
