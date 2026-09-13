import type { RecordingItem } from '../types/recordings'

export interface PlaybackOpenRequest {
  recording: RecordingItem
  seekSeconds: number
  forceCompatibility: boolean
}

export function makePlaybackOpenRequest(
  recording: RecordingItem,
  seekSeconds = 0,
  forceCompatibility = false,
): PlaybackOpenRequest {
  return {
    recording,
    seekSeconds: Number.isFinite(seekSeconds) ? Math.max(0, seekSeconds) : 0,
    forceCompatibility,
  }
}
