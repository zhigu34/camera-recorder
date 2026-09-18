import { describe, expect, it } from 'vitest'

import cameraSource from './CamerasView.vue?raw'
import editorSource from './CameraEditorDialog.vue?raw'
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

  it('loads adapter capabilities and uses the unified probe/create/update APIs', () => {
    expect(editorSource).toContain("'/api/camera-adapters'")
    expect(editorSource).toContain("'/api/camera-connections/probe'")
    expect(editorSource).toContain("'/api/cameras'")
    expect(editorSource).toContain(`/api/cameras/\${props.camera.id}`)
    expect(editorSource).toContain("'manual_rtsp'")
    expect(editorSource).toContain("'onvif'")
    expect(editorSource).toContain("'hik_sdk'")
    expect(editorSource).toContain('unavailable_reason')
  })

  it('blocks probe and save until adapter capabilities are known', () => {
    expect(editorSource).toContain("if (adaptersLoading.value) return '摄像头适配器能力仍在加载'")
    expect(editorSource).toContain("if (!selectedCapability.value) return '无法确认所选摄像头适配器能力'")
    expect(editorSource).toContain(':disabled="probing || adaptersLoading"')
    expect(editorSource).toContain(':disabled="saving || adaptersLoading || selectedAdapterUnavailable"')
  })

  it('explains adapter switches while preserving the camera identity and history', () => {
    expect(editorSource).toContain('Camera ID #{{ camera?.id }}')
    expect(editorSource).toContain('历史录像、事件和健康记录保持不变')
    expect(editorSource).toContain('可跳过检测直接保存')
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
