export interface TimelineRange {
  left: number
  width: number
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
