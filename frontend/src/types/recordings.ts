export interface ProxyProgress {
  mode?: 'live' | 'generate' | string
  elapsed_seconds?: number
  duration_seconds?: number
  source_offset_seconds?: number
  percent?: number | null
  running_seconds?: number
  cancellable?: boolean
}

export interface PlaybackState {
  state: 'direct' | 'ready' | 'needed' | 'generating' | 'streaming' | 'error'
  direct: boolean
  error?: string | null
  progress?: ProxyProgress | null
  video_codec?: string | null
  audio_codec?: string | null
  original_available?: boolean
  source_kind?: string
  remote_available?: boolean
  cloud_state?: string
  cloud_error?: string | null
  can_try_original?: boolean
}

export interface RecordingItem {
  id: number
  camera_id: number
  started_at?: string | null
  ended_at?: string | null
  duration?: number | null
  file_size?: number | null
  video_codec?: string | null
  audio_codec?: string | null
  width?: number | null
  height?: number | null
  fps?: number | null
  status: string
  health_status: string
  upload_status: string
  warning_count: number
  timestamp_warning_count?: number
  network_warning_count?: number
  filename: string
  playback: PlaybackState
}

export interface BrowserResult {
  camera_id: number
  date: string
  timezone: string
  count: number
  total_duration: number
  total_size: number
  items: RecordingItem[]
}
