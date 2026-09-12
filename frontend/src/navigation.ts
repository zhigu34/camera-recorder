import type { RouteLocationRaw } from 'vue-router'

export function cameraRoute(cameraId: number): RouteLocationRaw {
  return { path: '/cameras', query: { camera_id: String(cameraId) } }
}

export function eventRoute(eventId: number): RouteLocationRaw {
  return { path: '/events', query: { event_id: String(eventId) } }
}

export function recordingPlaybackRoute(recordingId: number, cameraId?: number | null): RouteLocationRaw {
  const query: Record<string, string> = { recording_id: String(recordingId) }
  if (cameraId) query.camera_id = String(cameraId)
  return { path: '/recordings/manage', query }
}

export function settingsSectionRoute(section: string): RouteLocationRaw {
  return { path: '/settings', query: { section } }
}
