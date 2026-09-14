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

  it('offers explicit global play and pause controls for the current layout', () => {
    expect(previewSource).toContain('function startAllVisibleSlots()')
    expect(previewSource).toContain('function pauseAllVisibleSlots()')
    expect(previewSource).toContain('@click="startAllVisibleSlots"')
    expect(previewSource).toContain('>全部播放</el-button>')
    expect(previewSource).toContain('@click="pauseAllVisibleSlots"')
    expect(previewSource).toContain('>全部暂停</el-button>')
    expect(previewSource).toContain('activeSlots.value.forEach((slot, index) => {')
    expect(previewSource).toContain('if (slot.cameraId === null) return')
    expect(previewSource).toContain('startSlot(index)')
    expect(previewSource).toContain('pauseSlot(index)')
  })

  it('does not invoke global playback controls during page mount', () => {
    const mountStart = previewSource.indexOf('onMounted(() => {')
    const mountEnd = previewSource.indexOf('onBeforeUnmount(() => {', mountStart)
    const mountBlock = previewSource.slice(mountStart, mountEnd)
    expect(mountBlock).not.toContain('startAllVisibleSlots')
    expect(mountBlock).not.toContain('pauseAllVisibleSlots')
    expect(mountBlock).not.toContain('startSlot(')
  })
})
