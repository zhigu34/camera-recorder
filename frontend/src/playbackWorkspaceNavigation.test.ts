import { describe, expect, it } from 'vitest'
import { playbackWallClockAction, resolvePlaybackSelection } from './utils/playbackWorkspaceNavigation'

const recordings = [
  { id: 10, started_at: '2026-09-13T10:00:00+08:00', ended_at: '2026-09-13T10:10:00+08:00', duration: 600 },
  { id: 11, started_at: '2026-09-13T10:20:00+08:00', ended_at: '2026-09-13T10:30:00+08:00', duration: 600 },
]

describe('playback workspace navigation', () => {
  it('seeks in place inside the current recording', () => {
    expect(playbackWallClockAction(10, recordings, 36030)).toEqual({
      kind: 'seek', wallSeconds: 36030, recordingId: 10, seekSeconds: 30, switchRecording: false,
    })
  })

  it('switches source for another recording', () => {
    expect(playbackWallClockAction(10, recordings, 37215)).toEqual({
      kind: 'seek', wallSeconds: 37215, recordingId: 11, seekSeconds: 15, switchRecording: true,
    })
  })

  it('keeps gaps as gaps', () => {
    expect(playbackWallClockAction(10, recordings, 36900)).toEqual({ kind: 'gap', wallSeconds: 36900 })
  })

  it('prefers a valid deep link and otherwise selects the first day recording', () => {
    expect(resolvePlaybackSelection(recordings, 11)?.id).toBe(11)
    expect(resolvePlaybackSelection(recordings, 999)?.id).toBe(10)
    expect(resolvePlaybackSelection([], 11)).toBeNull()
  })
})
