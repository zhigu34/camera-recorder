import { describe, expect, it } from 'vitest'
import { managementLocationForContext, playbackLocationForRecording } from './utils/recordingDeepLinks'

const recording = {
  id: 91,
  camera_id: 7,
  started_at: '2026-09-13T16:20:00+08:00',
  status: 'completed',
  health_status: 'healthy',
  upload_status: 'success',
  warning_count: 0,
  filename: '91.mp4',
  playback: { state: 'direct' as const, direct: true },
}

describe('recording deep links', () => {
  it('opens a managed recording in Playback', () => {
    expect(playbackLocationForRecording(recording)).toEqual({
      path: '/recordings/playback',
      query: { camera_id: '7', recording_id: '91', date: '2026-09-13' },
    })
  })

  it('opens Management without inventing a recording id', () => {
    expect(managementLocationForContext(7, '2026-09-13', null)).toEqual({
      path: '/recordings/manage',
      query: { camera_id: '7', date: '2026-09-13' },
    })
  })
})
