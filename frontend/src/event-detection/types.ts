export type EventSourceKind = 'local' | 'camera_native'
export type EventSourceStatus = 'available' | 'unavailable' | 'unsupported' | 'error'
export type DetectionEventType =
  | 'motion'
  | 'person'
  | 'vehicle'
  | 'intrusion'
  | 'tamper'
  | 'digital_input'
  | 'unknown'
export type MotionSensitivity = 'low' | 'medium' | 'high'

export interface CameraSummary {
  id: number
  name: string
  enabled: boolean
  status?: string
  connectivity_status?: string
  recorder_state?: string
  [key: string]: unknown
}

export interface MotionZoneRead {
  id: number
  camera_id: number
  name: string
  enabled: boolean
  polygon: [number, number][]
  created_at?: string
  updated_at?: string
}

export interface EventSourceDescriptor {
  id: string
  provider: string
  source_kind: EventSourceKind
  status: EventSourceStatus
  display_name: string
  capabilities: string[]
  configurable: boolean
  runtime_state?: string | null
  reason?: string | null
}

export interface EventSourceRead {
  descriptor: EventSourceDescriptor
  config: Record<string, unknown>
  zones: MotionZoneRead[]
}

export interface DetectionCapabilitySlot {
  event_type: DetectionEventType
  status: EventSourceStatus
  source_id?: string | null
  reason?: string | null
}

export interface EventDetectionOverview {
  camera: CameraSummary
  sources: EventSourceDescriptor[]
  capability_slots: DetectionCapabilitySlot[]
  enabled_source_ids: string[]
}

export interface DetectionEventRead {
  id: number
  camera_id: number
  source_kind: EventSourceKind
  provider: string
  event_type: DetectionEventType
  started_at: string
  ended_at: string
  confidence?: number | null
  zone_id?: number | null
  zone_name?: string | null
  recording_id?: number | null
  snapshot_url?: string | null
  metadata: Record<string, unknown>
}

export interface MotionSourceDraft {
  enabled: boolean
  sensitivity: MotionSensitivity
  analysis_fps: number
  analysis_width: number
  min_duration_ms: number
  merge_gap_ms: number
  event_min_interval_ms: number
}
