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

export interface TimelineSelectionRange {
  start: number
  end: number
}

export interface TimelineRecording {
  id: number
  started_at?: string | null
  ended_at?: string | null
  duration?: number | null
}

export interface TimelineMotionEvent {
  started_at?: string | null
  ended_at?: string | null
}

function round4(value: number) {
  return Math.round(value * 10_000) / 10_000
}

function clampDay(value: number) {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(86400, value))
}

export function normalizeTimelineRange(start: number, end: number, minDuration = 1): TimelineSelectionRange {
  let left = clampDay(Math.min(start, end))
  let right = clampDay(Math.max(start, end))
  const minimum = Math.max(0, Math.min(86400, Number.isFinite(minDuration) ? minDuration : 0))
  if (right - left >= minimum) return { start: left, end: right }
  if (left + minimum <= 86400) {
    right = left + minimum
  } else {
    right = 86400
    left = Math.max(0, right - minimum)
  }
  return { start: left, end: right }
}

export function resizeTimelineRange(
  range: TimelineSelectionRange,
  edge: 'start' | 'end',
  target: number,
  minDuration = 1,
): TimelineSelectionRange {
  const normalized = normalizeTimelineRange(range.start, range.end, minDuration)
  const minimum = Math.max(0, Math.min(86400, Number.isFinite(minDuration) ? minDuration : 0))
  const value = clampDay(target)
  if (edge === 'start') {
    return {
      start: Math.min(value, normalized.end - minimum),
      end: normalized.end,
    }
  }
  return {
    start: normalized.start,
    end: Math.max(value, normalized.start + minimum),
  }
}

export function moveTimelineRange(range: TimelineSelectionRange, deltaSeconds: number): TimelineSelectionRange {
  const normalized = normalizeTimelineRange(range.start, range.end, 0)
  const duration = normalized.end - normalized.start
  if (duration >= 86400) return { start: 0, end: 86400 }
  const delta = Number.isFinite(deltaSeconds) ? deltaSeconds : 0
  let start = normalized.start + delta
  let end = normalized.end + delta
  if (start < 0) {
    end -= start
    start = 0
  }
  if (end > 86400) {
    start -= end - 86400
    end = 86400
  }
  return { start: Math.max(0, start), end: Math.min(86400, end) }
}

export function wallClockSeconds(value?: string | null) {
  if (!value) return null
  const match = value.match(/T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?/)
  if (!match) return null
  const fraction = match[4] ? Number(`0.${match[4]}`) : 0
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]) + fraction
}

export function motionPlaybackStartSeconds(value?: string | null, prerollSeconds = 2) {
  const start = wallClockSeconds(value)
  if (start === null) return null
  const preroll = Number.isFinite(prerollSeconds) ? Math.max(0, prerollSeconds) : 0
  return clampDay(start - preroll)
}

export function clampViewport(start: number, span: number) {
  const safeSpan = Math.max(1, Math.min(86400, span))
  return Math.max(0, Math.min(86400 - safeSpan, start))
}

export function timeAtPointer(viewStart: number, viewSpan: number, pointerRatio: number) {
  const ratio = Math.max(0, Math.min(1, pointerRatio))
  return Math.max(0, Math.min(86400, viewStart + viewSpan * ratio))
}

export function timeAtTrackPointer(
  viewStart: number,
  viewSpan: number,
  clientX: number,
  trackLeft: number,
  trackWidth: number,
) {
  if (!Number.isFinite(trackWidth) || trackWidth <= 0) return timeAtPointer(viewStart, viewSpan, 0)
  const ratio = (clientX - trackLeft) / trackWidth
  return timeAtPointer(viewStart, viewSpan, ratio)
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

export function motionEventOverlapsRecordings(
  event: TimelineMotionEvent,
  recordings: TimelineRecording[],
) {
  const start = wallClockSeconds(event.started_at)
  if (start === null) return false
  const parsedEnd = wallClockSeconds(event.ended_at)
  const end = Math.max(start + 0.001, parsedEnd ?? start + 0.001)
  return recordings.some((recording) => {
    const range = recordingRange(recording)
    return Boolean(range && start < range.end && end > range.start)
  })
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
  const range = recordingRange(recording)
  if (!range) return 0
  return Math.max(0, Math.min(range.end - range.start, wallSeconds - range.start))
}
