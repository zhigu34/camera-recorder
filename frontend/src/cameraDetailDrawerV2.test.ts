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

  it('keeps only an aggregate event detection summary and deep link in the drawer', () => {
    expect(workspaceSource).toContain('事件检测')
    expect(workspaceSource).toContain('本地移动检测')
    expect(workspaceSource).toContain('前往配置')
    expect(workspaceSource).toContain('axios.get<EventDetectionOverview>')
    expect(workspaceSource).toContain('`/api/cameras/${cameraId}/event-detection`')
    expect(workspaceSource).toContain("enabled_source_ids.includes('local.motion')")
    expect(workspaceSource).toContain('eventDetectionRoute(selectedCameraId.value)')
    expect(workspaceSource).not.toContain('/event-detection/sources/local.motion')
    expect(workspaceSource).not.toContain('<MotionDetectionPanel')
  })
})
