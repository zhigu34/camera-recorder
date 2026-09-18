export type CameraAdapterId = 'manual_rtsp' | 'onvif' | 'hik_sdk'
export type CameraFormFactor = 'unknown' | 'bullet' | 'dome' | 'turret' | 'ptz' | 'doorbell' | 'indoor' | 'panoramic'
export type TimestampMode = 'native' | 'reconstruct' | 'wallclock'

export interface CameraAdapterCapability {
  id: CameraAdapterId
  label: string
  available: boolean
  unavailable_reason?: string | null
}

export interface ManualRtspConnectionConfig {
  port: number
  main_path: string
  sub_path?: string | null
}

export interface OnvifMediaProfile {
  token: string
  name: string
  encoding?: string | null
  width?: number | null
  height?: number | null
  fps?: number | null
  uri?: string | null
}

export interface OnvifConnectionConfig {
  port: number
  device_service_url?: string
  device_uuid?: string | null
  firmware_version?: string | null
  serial_number?: string | null
  hardware_id?: string | null
  capabilities?: Record<string, unknown>
  profiles?: OnvifMediaProfile[]
  recording_profile_token?: string | null
  preview_profile_token?: string | null
  detection_profile_token?: string | null
}

export interface HikConnectionConfig {
  sdk_port: number
  channel: number
  main_stream_type: number
  sub_stream_type: number
  device_serial?: string | null
  device_model?: string | null
  device_name?: string | null
}

export interface CameraConnectionRead {
  id: number
  adapter: CameraAdapterId
  host: string
  username: string
  password_set: boolean
  revision: number
  verification_status: string
  verified_at?: string | null
  last_error?: string | null
  config: ManualRtspConnectionConfig | OnvifConnectionConfig | HikConnectionConfig
}

export interface CameraEditorCamera {
  id: number
  name: string
  manufacturer?: string | null
  model?: string | null
  form_factor?: CameraFormFactor | string
  enabled: boolean
  auto_record?: boolean
  timestamp_mode?: TimestampMode | string
  connection?: CameraConnectionRead | null
  ip?: string
  rtsp_port?: number
  username?: string
  rtsp_path?: string
  sub_rtsp_path?: string | null
}

interface CameraEditorDraftBase {
  name: string
  manufacturer: string
  model: string
  form_factor: CameraFormFactor
  enabled: boolean
  auto_record: boolean
  timestamp_mode: TimestampMode
  host: string
  username: string
  password: string
}

export interface ManualRtspEditorDraft extends CameraEditorDraftBase {
  adapter: 'manual_rtsp'
  port: number
  main_path: string
  sub_path: string
}

export interface OnvifEditorDraft extends CameraEditorDraftBase {
  adapter: 'onvif'
  port: number
  device_service_url?: string
}

export interface HikEditorDraft extends CameraEditorDraftBase {
  adapter: 'hik_sdk'
  sdk_port: number
  channel: number
  main_stream_type: number
  sub_stream_type: number
}

export type CameraEditorDraft = ManualRtspEditorDraft | OnvifEditorDraft | HikEditorDraft

export interface CameraConnectionProbeResult {
  adapter: CameraAdapterId
  ok: boolean
  device: Record<string, unknown>
  media: Record<string, unknown>
  connection_cache: Record<string, unknown>
}
