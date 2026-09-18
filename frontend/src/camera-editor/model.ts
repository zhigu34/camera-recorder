import type {
  CameraEditorCamera,
  CameraEditorDraft,
  CameraFormFactor,
  HikConnectionConfig,
  ManualRtspConnectionConfig,
  OnvifConnectionConfig,
  TimestampMode,
} from './types'

function formFactor(value?: string | null): CameraFormFactor {
  return ['bullet', 'dome', 'turret', 'ptz', 'doorbell', 'indoor', 'panoramic'].includes(value || '')
    ? value as CameraFormFactor
    : 'unknown'
}

function timestampMode(value?: string | null): TimestampMode {
  return ['native', 'wallclock'].includes(value || '') ? value as TimestampMode : 'reconstruct'
}

function identity(camera: CameraEditorCamera) {
  return {
    name: camera.name,
    manufacturer: camera.manufacturer || '',
    model: camera.model || '',
    form_factor: formFactor(camera.form_factor),
    enabled: camera.enabled,
    auto_record: Boolean(camera.auto_record),
    timestamp_mode: timestampMode(camera.timestamp_mode),
  }
}

export function emptyCameraDraft(): CameraEditorDraft {
  return {
    ...{
      name: '',
      manufacturer: '',
      model: '',
      form_factor: 'unknown' as const,
      enabled: true,
      auto_record: false,
      timestamp_mode: 'reconstruct' as const,
      host: '',
      username: 'admin',
      password: '',
    },
    adapter: 'manual_rtsp',
    port: 554,
    main_path: '/ch1/main',
    sub_path: '',
  }
}

export function draftFromCamera(camera: CameraEditorCamera): CameraEditorDraft {
  const base = { ...identity(camera), password: '' }
  const connection = camera.connection

  if (connection?.adapter === 'onvif') {
    const config = connection.config as OnvifConnectionConfig
    return {
      ...base,
      adapter: 'onvif',
      host: connection.host,
      username: connection.username,
      port: config.port,
      device_service_url: config.device_service_url || '',
    }
  }

  if (connection?.adapter === 'hik_sdk') {
    const config = connection.config as HikConnectionConfig
    return {
      ...base,
      adapter: 'hik_sdk',
      host: connection.host,
      username: connection.username,
      sdk_port: config.sdk_port,
      channel: config.channel,
      main_stream_type: config.main_stream_type,
      sub_stream_type: config.sub_stream_type,
    }
  }

  if (connection?.adapter === 'manual_rtsp') {
    const config = connection.config as ManualRtspConnectionConfig
    return {
      ...base,
      adapter: 'manual_rtsp',
      host: connection.host,
      username: connection.username,
      port: config.port,
      main_path: config.main_path,
      sub_path: config.sub_path || '',
    }
  }

  return {
    ...base,
    adapter: 'manual_rtsp',
    host: camera.ip || '',
    username: camera.username || 'admin',
    port: camera.rtsp_port || 554,
    main_path: camera.rtsp_path || '/ch1/main',
    sub_path: camera.sub_rtsp_path || '',
  }
}

export function connectionFingerprint(draft: CameraEditorDraft): string {
  if (draft.adapter === 'manual_rtsp') {
    return JSON.stringify([
      draft.adapter,
      draft.host.trim(),
      draft.username.trim(),
      draft.password,
      draft.port,
      draft.main_path.trim(),
      draft.sub_path.trim(),
    ])
  }
  if (draft.adapter === 'onvif') {
    return JSON.stringify([
      draft.adapter,
      draft.host.trim(),
      draft.username.trim(),
      draft.password,
      draft.port,
      (draft.device_service_url || '').trim(),
    ])
  }
  return JSON.stringify([
    draft.adapter,
    draft.host.trim(),
    draft.username.trim(),
    draft.password,
    draft.sdk_port,
    draft.channel,
    draft.main_stream_type,
    draft.sub_stream_type,
  ])
}

function connectionPayload(draft: CameraEditorDraft, includePassword: boolean): Record<string, unknown> {
  const common: Record<string, unknown> = {
    adapter: draft.adapter,
    host: draft.host.trim(),
    username: draft.username.trim(),
  }
  if (includePassword && draft.password) common.password = draft.password

  if (draft.adapter === 'manual_rtsp') {
    return {
      ...common,
      port: draft.port,
      main_path: draft.main_path.trim(),
      sub_path: draft.sub_path.trim() || null,
    }
  }
  if (draft.adapter === 'onvif') {
    return {
      ...common,
      port: draft.port,
      ...((draft.device_service_url || '').trim()
        ? { device_service_url: (draft.device_service_url || '').trim() }
        : {}),
    }
  }
  return {
    ...common,
    sdk_port: draft.sdk_port,
    channel: draft.channel,
    main_stream_type: draft.main_stream_type,
    sub_stream_type: draft.sub_stream_type,
  }
}

function identityPayload(draft: CameraEditorDraft): Record<string, unknown> {
  return {
    name: draft.name.trim(),
    manufacturer: draft.manufacturer.trim() || null,
    model: draft.model.trim() || null,
    form_factor: draft.form_factor,
    enabled: draft.enabled,
    auto_record: draft.auto_record,
    timestamp_mode: draft.timestamp_mode,
  }
}

export function passwordRequired(camera: CameraEditorCamera | null, draft: CameraEditorDraft): boolean {
  return camera === null || camera.connection?.adapter !== draft.adapter
}

export function createPayloadFromDraft(draft: CameraEditorDraft): Record<string, unknown> {
  if (!draft.password) throw new Error('password is required for a new camera connection')
  return {
    ...identityPayload(draft),
    connection: connectionPayload(draft, true),
  }
}

export function updatePayloadFromDraft(
  camera: CameraEditorCamera,
  draft: CameraEditorDraft,
): Record<string, unknown> {
  const baseline = draftFromCamera(camera)
  const adapterChanged = camera.connection?.adapter
    ? camera.connection.adapter !== draft.adapter
    : draft.adapter !== 'manual_rtsp'
  if (adapterChanged && !draft.password) {
    throw new Error('password is required when switching camera adapter')
  }

  const payload = identityPayload(draft)
  if (connectionFingerprint(draft) !== connectionFingerprint(baseline)) {
    payload.connection = connectionPayload(draft, Boolean(draft.password))
  }
  return payload
}

export function probePayloadFromDraft(
  camera: CameraEditorCamera | null,
  draft: CameraEditorDraft,
): Record<string, unknown> {
  if (passwordRequired(camera, draft) && !draft.password) {
    throw new Error('password is required before probing this connection')
  }
  return {
    ...(camera ? { camera_id: camera.id } : {}),
    connection: connectionPayload(draft, Boolean(draft.password)),
  }
}
