import { describe, expect, it } from 'vitest'
import workspaceSource from './CamerasWorkspace.vue?raw'

describe('ONVIF camera integration', () => {
  it('exposes an ONVIF add flow from the camera workspace', () => {
    expect(workspaceSource).toContain("import OnvifCameraAddView from './OnvifCameraAddView.vue'")
    expect(workspaceSource).toContain('添加 ONVIF')
    expect(workspaceSource).toContain('<OnvifCameraAddView')
  })

  it('keeps normal camera media manual while ONVIF configuration is added', () => {
    expect(workspaceSource).not.toContain('startPreview()')
    expect(workspaceSource).not.toContain('autoplay')
  })
})
