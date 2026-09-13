import type { LocationQueryRaw, RouteLocationRaw } from 'vue-router'

export type RecordingMode = 'playback' | 'manage'

export function recordingModeFromMeta(value: unknown): RecordingMode {
  return value === 'manage' ? 'manage' : 'playback'
}

export function recordingTabLocation(
  mode: RecordingMode,
  query: LocationQueryRaw,
  hash = '',
): RouteLocationRaw {
  return {
    path: mode === 'manage' ? '/recordings/manage' : '/recordings/playback',
    query: { ...query },
    hash,
  }
}

export function recordingIntentPath(intent: 'view' | 'manage') {
  return intent === 'manage' ? '/recordings/manage' : '/recordings/playback'
}
