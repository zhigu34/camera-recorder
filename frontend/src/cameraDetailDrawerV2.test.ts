import { describe, expect, it } from 'vitest'

import workspaceSource from './CamerasWorkspace.vue?raw'
import cameraSource from './CamerasView.vue?raw'

describe('camera detail workspace', () => {
  it('exposes a stable extension slot in the persistent camera detail pane', () => {
    expect(cameraSource).toContain('class="camera-detail-pane"')
    expect(cameraSource).toContain('class="camera-detail-extension-slot"')
    expect(workspaceSource).toContain('.camera-detail-pane .camera-detail-extension-slot')
    expect(workspaceSource).not.toContain('.camera-detail-drawer .drawer-body-v2')
  })

  it('keeps current-camera shortcuts to playback and recording management', () => {
    expect(workspaceSource).toContain('class="camera-drawer-shortcuts"')
    expect(workspaceSource).toContain("path: '/recordings/playback'")
    expect(workspaceSource).toContain("path: '/recordings/manage'")
    expect(workspaceSource).toContain("camera_id: String(selectedCameraId.value)")
  })

  it('keeps only an aggregate event detection summary and deep link in the detail workspace', () => {
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
