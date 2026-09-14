import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const mediaControlsSource = readFileSync(new URL('./PlaybackMediaControls.vue', import.meta.url), 'utf8')
const transportBridgeSource = readFileSync(new URL('./PlaybackTransportControls.vue', import.meta.url), 'utf8')

describe('playback transport communication', () => {
  it('uses a scoped Pinia transport channel instead of window CustomEvents', () => {
    expect(mediaControlsSource).not.toContain('camera-recorder:playback-')
    expect(mediaControlsSource).not.toContain('new CustomEvent')
    expect(transportBridgeSource).not.toContain('camera-recorder:playback-')
    expect(transportBridgeSource).not.toContain('window.addEventListener')
    expect(mediaControlsSource).toContain('usePlaybackTransportStore')
    expect(transportBridgeSource).toContain('usePlaybackTransportStore')
  })

  it('keeps skip, rate and interval changes explicit in the component contract', () => {
    expect(mediaControlsSource).toContain("emit('skip', deltaSeconds)")
    expect(mediaControlsSource).toContain("emit('update:playbackRate', value)")
    expect(mediaControlsSource).toContain("emit('update:skipSeconds', value)")
  })
})
