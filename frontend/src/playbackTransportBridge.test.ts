import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const mediaControlsSource = readFileSync(new URL('./PlaybackMediaControls.vue', import.meta.url), 'utf8')
const workspaceSource = readFileSync(new URL('./PlaybackWorkspace.vue', import.meta.url), 'utf8')

describe('playback transport communication', () => {
  it('uses explicit component events instead of window CustomEvents', () => {
    expect(mediaControlsSource).not.toContain('camera-recorder:playback-')
    expect(mediaControlsSource).not.toContain('new CustomEvent')
    expect(workspaceSource).not.toContain('PlaybackTransportControls')
  })

  it('wires player transport events directly into workspace state', () => {
    expect(workspaceSource).toContain('@skip="skipPlayback"')
    expect(workspaceSource).toContain('@update:playback-rate="handlePlaybackRate"')
    expect(workspaceSource).toContain('@update:skip-seconds="handleSkipSeconds"')
  })
})
