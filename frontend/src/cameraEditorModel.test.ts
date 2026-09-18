import { describe, expect, it } from 'vitest'

import {
  createPayloadFromDraft,
  draftFromCamera,
  passwordRequired,
  probePayloadFromDraft,
  updatePayloadFromDraft,
} from './camera-editor/model'
import type { CameraEditorCamera, CameraEditorDraft } from './camera-editor/types'

function camera(adapter: 'manual_rtsp' | 'onvif' | 'hik_sdk'): CameraEditorCamera {
  const common = {
    id: 12,
    name: 'Warehouse East',
    manufacturer: 'Vendor',
    model: 'Model',
    form_factor: 'bullet',
    enabled: true,
    auto_record: false,
    timestamp_mode: 'reconstruct',
  } as const
  if (adapter === 'manual_rtsp') {
    return {
      ...common,
      connection: {
        id: 3,
        adapter,
        host: '192.0.2.10',
        username: 'viewer',
        password_set: true,
        revision: 4,
        verification_status: 'verified',
        config: { port: 8554, main_path: '/main', sub_path: '/sub' },
      },
    }
  }
  if (adapter === 'onvif') {
    return {
      ...common,
      connection: {
        id: 3,
        adapter,
        host: '192.0.2.20',
        username: 'viewer',
        password_set: true,
        revision: 4,
        verification_status: 'verified',
        config: { port: 80, device_service_url: 'http://192.0.2.20:80/onvif/device_service' },
      },
    }
  }
  return {
    ...common,
    connection: {
      id: 3,
      adapter,
      host: '192.0.2.30',
      username: 'admin',
      password_set: true,
      revision: 4,
      verification_status: 'verified',
      config: { sdk_port: 8000, channel: 2, main_stream_type: 0, sub_stream_type: 1 },
    },
  }
}

describe('camera editor model', () => {
  it('hydrates canonical connection fields for every adapter', () => {
    expect(draftFromCamera(camera('manual_rtsp'))).toMatchObject({
      adapter: 'manual_rtsp', host: '192.0.2.10', port: 8554, main_path: '/main', sub_path: '/sub',
    })
    expect(draftFromCamera(camera('onvif'))).toMatchObject({
      adapter: 'onvif',
      host: '192.0.2.20',
      port: 80,
      device_service_url: 'http://192.0.2.20:80/onvif/device_service',
    })
    expect(draftFromCamera(camera('hik_sdk'))).toMatchObject({
      adapter: 'hik_sdk', host: '192.0.2.30', sdk_port: 8000, channel: 2,
    })
  })

  it('creates unified payloads without requiring a probe result', () => {
    const draft: CameraEditorDraft = {
      ...draftFromCamera(camera('onvif')),
      name: 'New ONVIF',
      password: 'secret',
    }
    expect(createPayloadFromDraft(draft)).toMatchObject({
      name: 'New ONVIF',
      connection: {
        adapter: 'onvif',
        host: '192.0.2.20',
        username: 'viewer',
        password: 'secret',
        port: 80,
        device_service_url: 'http://192.0.2.20:80/onvif/device_service',
      },
    })
  })

  it('omits unchanged same-adapter connection and reuses stored password', () => {
    const source = camera('manual_rtsp')
    const draft = draftFromCamera(source)
    expect(passwordRequired(source, draft)).toBe(false)
    expect(updatePayloadFromDraft(source, draft)).not.toHaveProperty('connection')

    const changed = { ...draft, host: '192.0.2.11' }
    expect(updatePayloadFromDraft(source, changed)).toMatchObject({
      connection: {
        adapter: 'manual_rtsp',
        host: '192.0.2.11',
        username: 'viewer',
        port: 8554,
        main_path: '/main',
      },
    })
    expect((updatePayloadFromDraft(source, changed).connection as Record<string, unknown>)).not.toHaveProperty('password')
  })

  it('requires a fresh password for a cross-adapter switch and keeps camera id outside the payload', () => {
    const source = camera('manual_rtsp')
    const switched: CameraEditorDraft = {
      name: source.name,
      manufacturer: '',
      model: '',
      form_factor: 'bullet',
      enabled: true,
      auto_record: false,
      timestamp_mode: 'reconstruct',
      adapter: 'onvif',
      host: '198.51.100.8',
      port: 80,
      username: 'admin',
      password: '',
    }
    expect(passwordRequired(source, switched)).toBe(true)
    expect(() => updatePayloadFromDraft(source, switched)).toThrow('password is required')

    switched.password = 'new-secret'
    const payload = updatePayloadFromDraft(source, switched)
    expect(payload).not.toHaveProperty('id')
    expect(payload).toMatchObject({
      connection: { adapter: 'onvif', host: '198.51.100.8', password: 'new-secret' },
    })
  })

  it('builds optional probe payloads and reuses stored password for same-adapter edits', () => {
    const source = camera('hik_sdk')
    const draft = draftFromCamera(source)
    expect(probePayloadFromDraft(source, draft)).toEqual({
      camera_id: 12,
      connection: {
        adapter: 'hik_sdk',
        host: '192.0.2.30',
        username: 'admin',
        sdk_port: 8000,
        channel: 2,
        main_stream_type: 0,
        sub_stream_type: 1,
      },
    })
  })
})
