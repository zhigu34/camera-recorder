import { describe, expect, it } from 'vitest'

import cameraSource from './CamerasView.vue?raw'
import editorSource from './CameraEditorDialog.vue?raw'
import deletionSource from './CameraDeletionImpactDialog.vue?raw'
import historySource from './CameraHistoryPanel.vue?raw'
import navigationSource from './navigation.ts?raw'

describe('camera history and danger zone', () => {
  it('distinguishes unavailable adapters and recorder errors from connectivity state', () => {
    expect(cameraSource).toContain("'/api/camera-adapters'")
    expect(cameraSource).toContain("'adapter-unavailable'")
    expect(cameraSource).toContain("'unverified'")
    expect(cameraSource).toContain('cameras.value.filter(isIssue)')
    expect(cameraSource).toContain("'适配器不可用'")
    expect(cameraSource).toContain("'录像异常'")
    expect(cameraSource).toContain("'/api/recorder/status'")
    expect(cameraSource).toContain('continuous_failure_active === true')
    expect(cameraSource).toContain('runtimeErrorReason(camera)')
  })

  it('uses canonical connection state for camera endpoint and preview roles', () => {
    expect(cameraSource).toContain("connection?.adapter === 'hik_sdk'")
    expect(cameraSource).toContain("connection?.adapter === 'onvif'")
    expect(cameraSource).toContain('config?.preview_profile_token')
    expect(cameraSource).toContain("connection?.adapter === 'manual_rtsp'")
  })

  it('renders a camera-scoped history summary with deep links', () => {
    expect(cameraSource).toContain('<CameraHistoryPanel')
    expect(historySource).toContain('/deletion-impact')
    expect(historySource).toContain('cameraRecordingsRoute')
    expect(historySource).toContain('cameraActivityRoute')
    expect(historySource).toContain('cameraSystemEventsRoute')
    expect(historySource).toContain('cameraHealthRoute')
    expect(historySource).toContain('cameraUploadsRoute')
  })

  it('uses explicit disable/re-enable controls instead of an editor enabled switch', () => {
    expect(editorSource).not.toContain('label="启用设备"')
    expect(cameraSource).toContain('disableCamera')
    expect(cameraSource).toContain('enableCamera')
    expect(cameraSource).toContain('录像、连接探测与重连、移动检测和事件预录')
    expect(cameraSource).toContain('setCameraEnabled(camera, false)')
    expect(cameraSource).toContain('setCameraEnabled(camera, true)')
  })

  it('fetches deletion impact and only permits permanent delete with zero blockers', () => {
    expect(cameraSource).toContain('<CameraDeletionImpactDialog')
    expect(deletionSource).toContain('/deletion-impact')
    expect(deletionSource).toContain('impact?.can_delete')
    expect(deletionSource).toContain('不会提供级联删除')
    expect(deletionSource).toContain('confirmName.value === props.camera.name')
    expect(deletionSource).toContain("axios.delete")
  })

  it('rechecks deletion impact and restores blocker details on a backend 409 race', () => {
    expect(deletionSource).toContain("errorValue.response?.status === 409")
    expect(deletionSource).toContain('isDeletionImpact(detail)')
    expect(deletionSource).toContain('impact.value = detail')
    expect(deletionSource).toContain('已阻止永久删除')
  })

  it('keeps split-detail information architecture explicit in template order', () => {
    const markers = [
      'class="drawer-device-nav"',
      'class="device-overview"',
      'class="preview-section"',
      'class="detail-columns"',
      'class="detail-section detail-section-v2 runtime-section"',
      '<CameraDetailWorkspace',
      '<CameraHistoryPanel',
      'class="drawer-operation-panel',
      'class="camera-device-management',
      'class="drawer-danger-zone"',
    ]
    const positions = markers.map((marker) => cameraSource.indexOf(marker))
    expect(positions.every((position) => position >= 0)).toBe(true)
    expect([...positions].sort((a, b) => a - b)).toEqual(positions)
  })

  it('keeps delete in the right-pane danger zone', () => {
    expect(cameraSource).toContain('class="drawer-danger-zone"')
    expect(cameraSource).toContain('@click="openDeletionImpact(selectedCamera)"')
    expect(cameraSource).not.toContain('@click="removeCamera(')
  })

  it('defines camera-scoped navigation for every blocker destination', () => {
    expect(navigationSource).toContain('cameraRecordingsRoute')
    expect(navigationSource).toContain('cameraActivityRoute')
    expect(navigationSource).toContain('cameraSystemEventsRoute')
    expect(navigationSource).toContain('cameraHealthRoute')
    expect(navigationSource).toContain('cameraUploadsRoute')
  })
})
