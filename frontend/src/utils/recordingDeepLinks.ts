import type { RouteLocationRaw } from 'vue-router'
import type { RecordingItem } from '../types/recordings'

function dateOf(value?: string | null) {
  return value && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : null
}

export function playbackLocationForRecording(recording: RecordingItem): RouteLocationRaw {
  const query: Record<string, string> = {
    camera_id: String(recording.camera_id),
    recording_id: String(recording.id),
  }
  const date = dateOf(recording.started_at)
  if (date) query.date = date
  return { path: '/recordings/playback', query }
}

export function managementLocationForContext(
  cameraId: number | null,
  date: string | null,
  recordingId: number | null,
): RouteLocationRaw {
  const query: Record<string, string> = {}
  if (cameraId) query.camera_id = String(cameraId)
  if (date) query.date = date
  if (recordingId) query.recording_id = String(recordingId)
  return { path: '/recordings/manage', query }
}
