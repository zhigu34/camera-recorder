import { describe, expect, it } from 'vitest'

import discoverySource from './CameraDiscoveryDialog.vue?raw'
import editorSource from './CameraEditorDialog.vue?raw'

describe('camera LAN discovery dialog', () => {
  it('uses explicit adapter-specific discovery endpoints without credentials', () => {
    expect(discoverySource).toContain("'/api/camera-discovery/onvif'")
    expect(discoverySource).toContain("'/api/camera-discovery/rtsp'")
    expect(discoverySource).not.toContain('username')
    expect(discoverySource).not.toContain('password')
  })

  it('rescans when explicitly opened and supports manual rescan', () => {
    expect(discoverySource).toContain('watch(')
    expect(discoverySource).toContain('if (open) void scan()')
    expect(discoverySource).toContain('@click="scan"')
    expect(discoverySource).toContain('重新扫描')
  })

  it('keeps incomplete ONVIF candidates visible but unselectable', () => {
    expect(discoverySource).toContain(':disabled="!device.selectable"')
    expect(discoverySource).toContain('device.unavailable_reason')
    expect(discoverySource).toContain('device.device_service_url')
    expect(discoverySource).toContain('device.scopes')
  })

  it('integrates discovery only for Manual RTSP and ONVIF', () => {
    expect(editorSource).toContain("import CameraDiscoveryDialog from './CameraDiscoveryDialog.vue'")
    expect(editorSource).toContain("form.adapter === 'manual_rtsp' || form.adapter === 'onvif'")
    expect(editorSource).toContain('扫描局域网')
    expect(editorSource).toContain('<CameraDiscoveryDialog')
    expect(editorSource).not.toContain("form.adapter === 'hik_sdk' && discoveryVisible")
  })

  it('applies RTSP and ONVIF candidates without probing or saving', () => {
    expect(editorSource).toContain("selection.adapter === 'manual_rtsp'")
    expect(editorSource).toContain('form.value.port = 554')
    expect(editorSource).toContain("selection.adapter === 'onvif'")
    expect(editorSource).toContain('form.value.device_service_url = selection.device_service_url')
    expect(editorSource).not.toContain('applyDiscoverySelection(selection); void probeConnection()')
    expect(editorSource).not.toContain('applyDiscoverySelection(selection); void save()')
  })

  it('invalidates an explicit ONVIF service URL after manual authority changes', () => {
    expect(editorSource).toContain('onvifServiceAuthorityMatches')
    expect(editorSource).toContain("form.value.device_service_url = ''")
  })
})
