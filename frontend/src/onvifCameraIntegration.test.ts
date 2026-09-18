import { describe, expect, it } from 'vitest'

import cameraSource from './CamerasView.vue?raw'
import workspaceSource from './CamerasWorkspace.vue?raw'

describe('ONVIF camera integration', () => {
  it('routes ONVIF configuration through the unified camera editor', () => {
    expect(cameraSource).toContain("import CameraEditorDialog from './CameraEditorDialog.vue'")
    expect(cameraSource).toContain('<CameraEditorDialog')
    expect(workspaceSource).not.toContain("import OnvifCameraAddView from './OnvifCameraAddView.vue'")
    expect(workspaceSource).not.toContain('<OnvifCameraAddView')
    expect(workspaceSource).not.toContain('添加 ONVIF')
  })

  it('keeps normal camera media manual while ONVIF configuration is edited', () => {
    expect(cameraSource).not.toContain('autoplay')
    expect(workspaceSource).not.toContain('autoplay')
  })
})
