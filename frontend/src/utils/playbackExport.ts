import type {
  ExportCreatePayload,
  ExportGapPolicy,
  ExportMode,
  ExportPackageMode,
  ExportRange,
} from '../types/exports'
import { wallClockSeconds, type TimelineRecording } from './playbackTimelineV3'

function pad2(value: number) {
  return String(value).padStart(2, '0')
}

function addCalendarDays(date: string, days: number) {
  const [year, month, day] = date.split('-').map(Number)
  const value = new Date(Date.UTC(year, month - 1, day + days))
  return `${value.getUTCFullYear()}-${pad2(value.getUTCMonth() + 1)}-${pad2(value.getUTCDate())}`
}

function offsetLabel(offsetMinutes: number) {
  const eastMinutes = -offsetMinutes
  const sign = eastMinutes >= 0 ? '+' : '-'
  const absolute = Math.abs(eastMinutes)
  return `${sign}${pad2(Math.floor(absolute / 60))}:${pad2(absolute % 60)}`
}

function isoTimezoneOffsetMinutes(value?: string | null) {
  if (!value) return null
  if (/Z$/i.test(value)) return 0
  const match = value.match(/([+-])(\d{2}):(\d{2})$/)
  if (!match) return null
  const eastMinutes = (Number(match[2]) * 60 + Number(match[3])) * (match[1] === '+' ? 1 : -1)
  return -eastMinutes
}

export function recordingTimezoneOffsetMinutes(
  recordings: TimelineRecording[],
  fallback = new Date().getTimezoneOffset(),
) {
  for (const recording of recordings) {
    const offset = isoTimezoneOffsetMinutes(recording.started_at) ?? isoTimezoneOffsetMinutes(recording.ended_at)
    if (offset !== null) return offset
  }
  return fallback
}

export function wallClockIso(
  date: string,
  seconds: number,
  timezoneOffsetMinutes = new Date().getTimezoneOffset(),
) {
  const safe = Math.max(0, Math.min(86400, Number.isFinite(seconds) ? Math.round(seconds) : 0))
  const dayOffset = safe === 86400 ? 1 : 0
  const secondsInDay = safe === 86400 ? 0 : safe
  const hour = Math.floor(secondsInDay / 3600)
  const minute = Math.floor((secondsInDay % 3600) / 60)
  const second = secondsInDay % 60
  return `${addCalendarDays(date, dayOffset)}T${pad2(hour)}:${pad2(minute)}:${pad2(second)}${offsetLabel(timezoneOffsetMinutes)}`
}

export function initialExportRange(
  activeWallSeconds: number | null | undefined,
  recordings: TimelineRecording[],
): ExportRange {
  let start = typeof activeWallSeconds === 'number' && Number.isFinite(activeWallSeconds)
    ? Math.max(0, Math.min(86400, activeWallSeconds))
    : null
  if (start === null) {
    const candidates = recordings
      .map((item) => wallClockSeconds(item.started_at))
      .filter((value): value is number => value !== null && Number.isFinite(value))
    start = candidates.length ? Math.min(...candidates) : 12 * 3600
  }
  if (start >= 86400) start = Math.max(0, 86400 - 300)
  return { start, end: Math.min(86400, start + 300) }
}

export function availablePackageModes(
  gapPolicy: ExportGapPolicy,
  hasGaps: boolean,
): ExportPackageMode[] {
  return gapPolicy === 'split' && hasGaps ? ['individual', 'zip'] : ['individual']
}

export function buildExportRequest(options: {
  cameraId: number
  date: string
  range: ExportRange
  exportMode: ExportMode
  gapPolicy: ExportGapPolicy
  packageMode: ExportPackageMode
  timezoneOffsetMinutes?: number
}): ExportCreatePayload {
  const offset = options.timezoneOffsetMinutes ?? new Date().getTimezoneOffset()
  return {
    camera_id: options.cameraId,
    start_at: wallClockIso(options.date, options.range.start, offset),
    end_at: wallClockIso(options.date, options.range.end, offset),
    export_mode: options.exportMode,
    gap_policy: options.gapPolicy,
    package_mode: options.packageMode,
  }
}
