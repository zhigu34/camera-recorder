import { describe, expect, it } from 'vitest'
import previewSource from './PreviewViewV2.vue?raw'

describe('Live preview action semantics', () => {
  it('uses a single central primary action for only the current tile', () => {
    expect(previewSource).toContain('class="tile-primary-overlay"')
    expect(previewSource).toContain('@click.stop="toggleSlotPlayback(index)"')
    expect(previewSource).toContain('function startSlot(index: number)')
    expect(previewSource).toContain('function pauseSlot(index: number)')
    expect(previewSource).toContain('slots: [{ index, camera_id: slot.cameraId, stream: slot.stream }]')
  })

  it('keeps secondary actions outside the central overlay', () => {
    const primaryStart = previewSource.indexOf('class="tile-primary-overlay"')
    const primaryEnd = previewSource.indexOf('class="tile-error-copy"', primaryStart)
    const primaryBlock = previewSource.slice(primaryStart, primaryEnd)
    expect(primaryBlock).not.toContain('enterFullscreen')
    expect(primaryBlock).not.toContain('openCameraConfig')
    expect(primaryBlock).not.toContain('setStream')
    expect(primaryBlock).not.toContain('clearSlot')

    expect(previewSource).toContain('class="tile-edge-tools desktop-tools"')
    expect(previewSource).toContain('@click="openCameraConfig(slot.cameraId)"')
    expect(previewSource).toContain('@click="enterFullscreen(index)"')
    expect(previewSource).toContain('@click="clearSlot(index)"')
  })

  it('keeps recording playback as a separate peripheral action', () => {
    expect(previewSource).toContain('title="录像回放" @click="openPlayback"')
    expect(previewSource).toContain('<Clock />')
  })
})
