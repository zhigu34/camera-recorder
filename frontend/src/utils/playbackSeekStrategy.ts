export type PlaybackSeekStrategy = 'in-place' | 'switch-recording'

export function playbackSeekStrategy(
  currentRecordingId: number | null | undefined,
  targetRecordingId: number,
): PlaybackSeekStrategy {
  return currentRecordingId === targetRecordingId ? 'in-place' : 'switch-recording'
}
