import {
  findRecordingAtWallTime,
  recordingSeekOffset,
  type TimelineRecording,
} from './playbackTimelineV3'

export type PlaybackWallClockAction =
  | { kind: 'gap'; wallSeconds: number }
  | {
      kind: 'seek'
      wallSeconds: number
      recordingId: number
      seekSeconds: number
      switchRecording: boolean
    }

export function playbackWallClockAction(
  currentRecordingId: number | null,
  recordings: TimelineRecording[],
  wallSeconds: number,
): PlaybackWallClockAction {
  const recording = findRecordingAtWallTime(recordings, wallSeconds)
  if (!recording) return { kind: 'gap', wallSeconds }

  return {
    kind: 'seek',
    wallSeconds,
    recordingId: recording.id,
    seekSeconds: recordingSeekOffset(recording, wallSeconds),
    switchRecording: recording.id !== currentRecordingId,
  }
}

export function resolvePlaybackSelection(
  recordings: TimelineRecording[],
  recordingId: number | null,
): TimelineRecording | null {
  if (recordingId) {
    const exact = recordings.find((item) => item.id === recordingId)
    if (exact) return exact
  }
  return recordings[0] || null
}
