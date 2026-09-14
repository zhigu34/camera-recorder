import { describe, expect, it, vi } from 'vitest'

import {
  DEFAULT_SKIP_INTERVAL,
  PLAYBACK_RATES,
  SKIP_INTERVALS,
  SKIP_INTERVAL_STORAGE_KEY,
  loadSkipInterval,
  normalizePlaybackRate,
  normalizeSkipInterval,
  playbackSkipTarget,
  saveSkipInterval,
} from './utils/playbackTransport'

import controlsSource from './PlaybackTransportControls.vue?raw'
import playerSource from './PlaybackPlayer.vue?raw'
import workspaceSource from './PlaybackWorkspace.vue?raw'

describe('playback transport helpers', () => {
  it('accepts only the fixed playback rates and skip intervals', () => {
    expect(PLAYBACK_RATES).toEqual([0.5, 1, 1.5, 2, 4])
    expect(SKIP_INTERVALS).toEqual([5, 10, 15, 20, 25, 30])
    expect(normalizePlaybackRate(2)).toBe(2)
    expect(normalizePlaybackRate(3)).toBe(1)
    expect(normalizeSkipInterval(25)).toBe(25)
    expect(normalizeSkipInterval(31)).toBe(DEFAULT_SKIP_INTERVAL)
  })

  it('clamps skip targets to the current day', () => {
    expect(playbackSkipTarget(100, -30)).toBe(70)
    expect(playbackSkipTarget(10, -30)).toBe(0)
    expect(playbackSkipTarget(86390, 30)).toBe(86400)
    expect(playbackSkipTarget(null, 10)).toBeNull()
  })

  it('loads and saves the selected skip interval safely', () => {
    const storage = {
      getItem: vi.fn(() => '20'),
      setItem: vi.fn(),
    }
    expect(loadSkipInterval(storage)).toBe(20)
    expect(saveSkipInterval(30, storage)).toBe(30)
    expect(storage.setItem).toHaveBeenCalledWith(SKIP_INTERVAL_STORAGE_KEY, '30')

    storage.getItem.mockReturnValue('999')
    expect(loadSkipInterval(storage)).toBe(DEFAULT_SKIP_INTERVAL)
  })
})

describe('playback transport integration', () => {
  it('keeps skip, rate, and interval controls in the playback workspace', () => {
    expect(controlsSource).toContain('回放控制')
    expect(controlsSource).toContain('播放倍速')
    expect(controlsSource).toContain('快进倒退秒数')
    expect(workspaceSource).toContain('<PlaybackTransportControls')
    expect(workspaceSource).toContain('@skip="skipPlayback"')
    expect(workspaceSource).toContain(':playback-rate="playbackRate"')
    expect(workspaceSource).toContain('saveSkipInterval(value, playbackStorage())')
  })

  it('applies playbackRate without changing the manual-start policy', () => {
    expect(playerSource).toContain('video.playbackRate = normalizePlaybackRate(props.playbackRate)')
    expect(playerSource).toContain('watch(() => props.playbackRate, applyPlaybackRate)')
    expect(playerSource).toContain('v-else-if="activeRecording && isPlayable(activeRecording)"')
    expect(playerSource).toContain('@click="open(activeRecording)"')
  })
})
