import { describe, expect, it } from 'vitest'

import cameraSource from './CamerasView.vue?raw'
import workspaceSource from './CamerasWorkspace.vue?raw'

describe('unified camera editor', () => {
  it('uses one reusable editor for add and edit actions', () => {
    expect(cameraSource).toContain("import CameraEditorDialog from './CameraEditorDialog.vue'")
    expect(cameraSource).toContain('<CameraEditorDialog')
    expect(cameraSource).toContain('@saved="handleEditorSaved"')
    expect(cameraSource).toContain('@click="openCreate"')
    expect(cameraSource).toContain('@click="openEdit(selectedCamera)"')
  })

  it('retires standalone HIK and ONVIF workspace add modals', () => {
    expect(workspaceSource).not.toContain("import HikCameraAddView from './HikCameraAddView.vue'")
    expect(workspaceSource).not.toContain("import OnvifCameraAddView from './OnvifCameraAddView.vue'")
    expect(workspaceSource).not.toContain('<HikCameraAddView')
    expect(workspaceSource).not.toContain('<OnvifCameraAddView')
    expect(workspaceSource).not.toContain('添加 HIK SDK')
    expect(workspaceSource).not.toContain('添加 ONVIF')
  })

  it('keeps batch add and the persistent detail extension workspace', () => {
    expect(workspaceSource).toContain("import BatchCamerasView from './BatchCamerasView.vue'")
    expect(workspaceSource).toContain('<BatchCamerasView')
    expect(workspaceSource).toContain('.camera-detail-pane .camera-detail-extension-slot')
    expect(workspaceSource).toContain("path: '/recordings/playback'")
    expect(workspaceSource).toContain("path: '/recordings/manage'")
    expect(workspaceSource).toContain('eventDetectionRoute')
  })
})
