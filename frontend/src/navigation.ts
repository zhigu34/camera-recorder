import type { RouteLocationRaw } from 'vue-router'

export function cameraRoute(cameraId: number): RouteLocationRaw {
  return { path: '/cameras', query: { camera_id: String(cameraId) } }
}

export function eventDetectionRoute(cameraId?: number | null): RouteLocationRaw {
  if (!cameraId) return { path: '/event-detection' }
  return { path: '/event-detection', query: { camera_id: String(cameraId) } }
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

export function cameraRecordingsRoute(cameraId: number): RouteLocationRaw {
  return { path: '/recordings/manage', query: { camera_id: String(cameraId) } }
}

export function cameraActivityRoute(cameraId: number): RouteLocationRaw {
  return { path: '/events', query: { camera_id: String(cameraId) } }
}

export function cameraSystemEventsRoute(cameraId: number): RouteLocationRaw {
  return { path: '/events', query: { camera_id: String(cameraId), view: 'system' } }
}

export function cameraHealthRoute(cameraId: number): RouteLocationRaw {
  return { path: '/health-center', query: { camera_id: String(cameraId) } }
}

export function cameraUploadsRoute(cameraId: number): RouteLocationRaw {
  return { path: '/uploads', query: { camera_id: String(cameraId) } }
}
