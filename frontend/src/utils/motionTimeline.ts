export interface TimelineRange {
  left: number
  width: number
}

export interface MotionEventLike {
  recording_id?: number | null
  started_at: string
}

export interface MotionRecordingLike {
  id: number
  started_at?: string | null
  ended_at?: string | null
  duration?: number | null
}

function round4(value: number) {
  return Math.round(value * 10_000) / 10_000
}

function wallClockMilliseconds(value: string) {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?/)
  if (!match) return null
  const milliseconds = Number((match[7] || '').padEnd(3, '0').slice(0, 3))
  return Date.UTC(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
    Number(match[4]),
    Number(match[5]),
    Number(match[6]),
    milliseconds,
  )
}

export function timelineRange(
  startSeconds: number,
  endSeconds: number,
  viewportStart: number,
  viewportEnd: number,
): TimelineRange | null {
  if (!Number.isFinite(startSeconds) || !Number.isFinite(endSeconds)) return null
  if (!Number.isFinite(viewportStart) || !Number.isFinite(viewportEnd) || viewportEnd <= viewportStart) return null
  if (endSeconds <= viewportStart || startSeconds >= viewportEnd || endSeconds <= startSeconds) return null

  const clippedStart = Math.max(startSeconds, viewportStart)
  const clippedEnd = Math.min(endSeconds, viewportEnd)
  const span = viewportEnd - viewportStart
  return {
    left: round4(((clippedStart - viewportStart) / span) * 100),
    width: round4(((clippedEnd - clippedStart) / span) * 100),
  }
}

export function eventSeekOffset(eventStartedAt: string, recordingStartedAt: string, leadSeconds = 2) {
  const eventMs = wallClockMilliseconds(eventStartedAt)
  const recordingMs = wallClockMilliseconds(recordingStartedAt)
  if (eventMs === null || recordingMs === null) return 0
  return Math.max(0, (eventMs - recordingMs) / 1000 - Math.max(0, leadSeconds))
}

export function findMotionRecording<T extends MotionRecordingLike>(event: MotionEventLike, recordings: T[]): T | null {
  if (event.recording_id) {
    const exact = recordings.find((item) => item.id === event.recording_id)
    if (exact) return exact
  }

  const eventMs = wallClockMilliseconds(event.started_at)
  if (eventMs === null) return null

  for (const item of recordings) {
    if (!item.started_at) continue
    const startMs = wallClockMilliseconds(item.started_at)
    if (startMs === null) continue
    const explicitEndMs = item.ended_at ? wallClockMilliseconds(item.ended_at) : null
    const durationMs = Math.max(0, Number(item.duration || 0)) * 1000
    const endMs = explicitEndMs ?? (durationMs ? startMs + durationMs : startMs)
    if (eventMs >= startMs && eventMs <= endMs) return item
  }
  return null
}

export function clockSeconds(value?: string | null) {
  if (!value) return null
  const match = value.match(/T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?/)
  if (!match) return null
  const fraction = match[4] ? Number(`0.${match[4]}`) : 0
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]) + fraction
}

export function dayQueryRange(date: string) {
  return {
    start: `${date}T00:00:00`,
    end: `${date}T23:59:59.999999`,
  }
}
