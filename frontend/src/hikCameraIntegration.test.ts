import { describe, expect, it } from 'vitest'
import workspaceSource from './CamerasWorkspace.vue?raw'
import hikSource from './HikCameraAddView.vue?raw'

describe('HIK SDK camera integration', () => {
  it('exposes HIK and ONVIF as explicit adapter add flows', () => {
    expect(workspaceSource).toContain("import HikCameraAddView from './HikCameraAddView.vue'")
    expect(workspaceSource).toContain('添加 HIK SDK')
    expect(workspaceSource).toContain('<HikCameraAddView')
    expect(workspaceSource).toContain('添加 ONVIF')
  })

  it('requires explicit probe then create and does not autoplay media', () => {
    expect(hikSource).toContain("'/api/cameras/hik/probe'")
    expect(hikSource).toContain("'/api/cameras/hik'")
    expect(hikSource).toContain('请先检测 HIK SDK 设备')
    expect(hikSource).not.toContain('autoplay')
    expect(hikSource).not.toContain('preview.mjpeg')
  })
})
