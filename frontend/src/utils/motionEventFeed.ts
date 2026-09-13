import {
  motionEventOverlapsRecordings,
  wallClockSeconds,
  type TimelineRecording,
} from './playbackTimelineV3'

export interface MotionFeedEvent {
  id: number
  camera_id: number
  zone_id?: number | null
  recording_id?: number | null
  started_at: string
  ended_at: string
  snapshot_path?: string | null
  peak_score?: number | null
  metadata_json?: string | null
}

export interface MotionFeedZone {
  id: number
  name: string
}

export function prepareMotionEventFeed<T extends MotionFeedEvent>(events: T[], recordings: TimelineRecording[]) {
  return events
    .filter((event) => motionEventOverlapsRecordings(event, recordings))
    .slice()
    .sort((left, right) => (wallClockSeconds(right.started_at) || 0) - (wallClockSeconds(left.started_at) || 0))
}

export function motionEventDuration(event: Pick<MotionFeedEvent, 'started_at' | 'ended_at'>) {
  const start = wallClockSeconds(event.started_at)
  const end = wallClockSeconds(event.ended_at)
  if (start === null || end === null) return 0
  return Math.max(0, end >= start ? end - start : 86400 - start + end)
}

export function motionEventSeekTarget(event: Pick<MotionFeedEvent, 'started_at'>, leadSeconds = 2) {
  const start = wallClockSeconds(event.started_at)
  if (start === null) return 0
  return Math.max(0, start - Math.max(0, leadSeconds))
}

export function motionEventZoneLabel(event: Pick<MotionFeedEvent, 'zone_id'>, zones: MotionFeedZone[]) {
  if (!event.zone_id) return '全画面'
  return zones.find((zone) => zone.id === event.zone_id)?.name || `区域 #${event.zone_id}`
}

export function motionEventSnapshotUrl(event: Pick<MotionFeedEvent, 'id'>) {
  return `/api/motion-events/${event.id}/snapshot`
}
