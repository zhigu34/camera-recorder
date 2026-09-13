import { describe, expect, it } from 'vitest'
import previewSource from './PreviewView.vue?raw'

describe('Live preview action semantics', () => {
  it('uses the play icon to start live monitoring instead of navigating to playback', () => {
    expect(previewSource).toContain('function startMonitoring()')
    expect(previewSource).toContain('title="播放实时画面" @click="startMonitoring"><VideoPlay /></button>')
    expect(previewSource).not.toContain('title="录像回放" @click="openPlayback"><VideoPlay /></button>')
  })

  it('keeps recording playback as a separate clock action', () => {
    expect(previewSource).toContain('Clock,')
    expect(previewSource).toContain('title="录像回放" @click="openPlayback"><Clock /></button>')
  })
})
