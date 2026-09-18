import { describe, expect, it } from 'vitest'

import cameraSource from './CamerasView.vue?raw'
import workspaceSource from './CamerasWorkspace.vue?raw'

describe('HIK SDK camera integration', () => {
  it('routes HIK configuration through the unified camera editor', () => {
    expect(cameraSource).toContain("import CameraEditorDialog from './CameraEditorDialog.vue'")
    expect(cameraSource).toContain('<CameraEditorDialog')
    expect(workspaceSource).not.toContain("import HikCameraAddView from './HikCameraAddView.vue'")
    expect(workspaceSource).not.toContain('<HikCameraAddView')
    expect(workspaceSource).not.toContain('添加 HIK SDK')
  })

  it('keeps camera media manual while HIK configuration is edited', () => {
    expect(cameraSource).not.toContain('autoplay')
    expect(workspaceSource).not.toContain('autoplay')
  })
})
