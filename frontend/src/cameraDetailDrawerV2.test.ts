import { describe, expect, it } from 'vitest'

import workspaceSource from './CamerasWorkspace.vue?raw'
import cameraSource from './CamerasView.vue?raw'
import detailSource from './CameraDetailWorkspace.vue?raw'

describe('camera detail workspace', () => {
  it('renders an explicit detail workspace inside the persistent camera pane', () => {
    expect(cameraSource).toContain('class="camera-detail-pane"')
    expect(cameraSource).toContain('<CameraDetailWorkspace')
    expect(workspaceSource).not.toContain('<Teleport')
    expect(workspaceSource).not.toContain('MutationObserver')
  })

  it('keeps current-camera shortcuts to playback and recording management', () => {
    expect(detailSource).toContain('class="camera-drawer-shortcuts"')
    expect(detailSource).toContain("path: '/recordings/playback'")
    expect(detailSource).toContain("path: '/recordings/manage'")
    expect(detailSource).toContain('camera_id: String(props.cameraId)')
  })

  it('keeps only an aggregate event detection summary and deep link in the detail workspace', () => {
    expect(detailSource).toContain('事件检测')
    expect(detailSource).toContain('本地移动检测')
    expect(detailSource).toContain('前往配置')
    expect(detailSource).toContain('axios.get<EventDetectionOverview>')
    expect(detailSource).toContain('`/api/cameras/${cameraId}/event-detection`')
    expect(detailSource).toContain("enabled_source_ids.includes('local.motion')")
    expect(detailSource).toContain('eventDetectionRoute(props.cameraId)')
    expect(detailSource).not.toContain('/event-detection/sources/local.motion')
    expect(detailSource).not.toContain('<MotionDetectionPanel')
  })
})
