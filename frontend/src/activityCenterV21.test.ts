import { describe, expect, it } from 'vitest'

import eventCenterSource from './EventCenterView.vue?raw'
import playbackSource from './PlaybackWorkspace.vue?raw'

describe('activity center v2.1 semantics', () => {
  it('receives realtime motion activities from the shared event websocket', () => {
    expect(eventCenterSource).toContain('after_motion_id')
    expect(eventCenterSource).toContain("message.type === 'motion.created'")
    expect(eventCenterSource).toContain('mergeActivityEvent')
  })

  it('starts direct motion-event playback two seconds before detection begins', () => {
    expect(eventCenterSource).toContain('motionPlaybackStartSeconds')
    expect(eventCenterSource).toContain('motionPlaybackStartSeconds(event.started_at)')
  })

  it('offers padded event playback and direct event clip export from activity detail', () => {
    expect(eventCenterSource).toContain('播放前后 10 秒')
    expect(eventCenterSource).toContain('导出事件片段')
    expect(eventCenterSource).toContain("'/api/exports/analyze'")
    expect(eventCenterSource).toContain("'/api/exports'")
    expect(eventCenterSource).toContain('play_until_wall_seconds')

    expect(playbackSource).toContain('play_until_wall_seconds')
    expect(playbackSource).toContain('playerRef.value?.pause()')
  })

  it('paginates the existing filtered system event list at 50 rows by default', () => {
    expect(eventCenterSource).toContain('const systemPageSize = ref(50)')
    expect(eventCenterSource).toContain('paginatedEvents')
    expect(eventCenterSource).toContain(':data="paginatedEvents"')
    expect(eventCenterSource).toContain('<el-pagination')
  })
})
