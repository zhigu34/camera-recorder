import { describe, expect, it } from 'vitest'

import workspaceSource from './CamerasWorkspace.vue?raw'
import mainSource from './main.ts?raw'

describe('camera detail drawer v2', () => {
  it('loads the v2 refinement layer after the existing drawer styles', () => {
    const baseIndex = mainSource.indexOf("./styles/camera-detail-drawer.css")
    const v2Index = mainSource.indexOf("./styles/camera-detail-drawer-v2.css")
    expect(baseIndex).toBeGreaterThan(-1)
    expect(v2Index).toBeGreaterThan(baseIndex)
  })

  it('adds current-camera shortcuts to playback and recording management', () => {
    expect(workspaceSource).toContain('class="camera-drawer-shortcuts"')
    expect(workspaceSource).toContain("path: '/recordings/playback'")
    expect(workspaceSource).toContain("path: '/recordings/manage'")
    expect(workspaceSource).toContain("camera_id: String(selectedCameraId.value)")
  })

  it('keeps motion detection in the existing drawer portal instead of creating a second settings surface', () => {
    expect(workspaceSource).toContain('to=".camera-detail-drawer .drawer-body-v2"')
    expect(workspaceSource).toContain('<MotionDetectionPanel')
  })
})
