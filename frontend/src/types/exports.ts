import type { TimelineSelectionRange } from '../utils/playbackTimelineV3'

export type ExportMode = 'fast' | 'exact'
export type ExportGapPolicy = 'merge' | 'split'
export type ExportPackageMode = 'individual' | 'zip'
export type ExportStatus = 'pending' | 'processing' | 'ready' | 'failed' | 'expired'
export type ExportArtifactKind = 'mp4' | 'zip' | 'manifest'

export type ExportRange = TimelineSelectionRange

export interface ExportInterval {
  start_at: string
  end_at: string
  duration: number
}

export interface ExportGroup extends ExportInterval {
  recording_ids: number[]
}

export interface ExportRangeAnalysis {
  camera_id: number
  requested_start_at: string
  requested_end_at: string
  recording_count: number
  unavailable_count: number
  requested_duration: number
  covered_duration: number
  continuous_groups: ExportGroup[]
  gaps: ExportInterval[]
  unavailable_intervals: ExportInterval[]
  exportable: boolean
}

export interface ExportCreatePayload {
  camera_id: number
  start_at: string
  end_at: string
  export_mode: ExportMode
  gap_policy: ExportGapPolicy
  package_mode: ExportPackageMode
}

export interface ExportJob {
  id: number
  camera_id: number
  requested_start_at: string
  requested_end_at: string
  export_mode: ExportMode
  gap_policy: ExportGapPolicy
  package_mode: ExportPackageMode
  status: ExportStatus
  progress: number
  gap_count: number
  requested_duration: number
  covered_duration: number
  error_message?: string | null
  created_at: string
  started_at?: string | null
  completed_at?: string | null
  expires_at?: string | null
}

export interface ExportArtifact {
  id: number
  export_job_id: number
  kind: ExportArtifactKind
  segment_index?: number | null
  start_at?: string | null
  end_at?: string | null
  file_size: number
  created_at: string
}
