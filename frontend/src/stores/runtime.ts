import axios from 'axios'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export type RuntimeSocketState = 'connecting' | 'connected' | 'disconnected'

export interface RecordingStats {
  segments: number
  unhealthy_segments: number
  failed_segments: number
  warning_count: number
  timestamp_warning_count: number
  network_warning_count: number
}

export interface TimestampGuidance {
  suggested_mode: string | null
  message: string
}

export interface CameraHealth {
  camera_id: number
  name: string
  ip: string
  enabled: boolean
  expected_recording: boolean
  connectivity_status: 'unknown' | 'online' | 'offline'
  recorder_state: string
  schedule_state: string
  state?: string
  abnormal: boolean
  restart_count: number
  timestamp_mode?: string
  timestamp_warning_count?: number
  timestamp_guidance?: TimestampGuidance | null
  started_at?: string | null
  last_error?: string | null
  recordings_24h?: RecordingStats
}

export interface StorageCleanup {
  running: boolean
  last_run_at: string | null
  last_result: string | null
  deleted_files: number
  freed_bytes: number
  last_error: string | null
}

export interface HealthSnapshot {
  generated_at: string
  uptime_seconds: number
  cameras: {
    total: number
    enabled: number
    recording: number
    reconnecting: number
    abnormal: number
    online: number
    offline: number
    unknown: number
  }
  recordings_24h: RecordingStats
  uploads: Record<string, number>
  storage: {
    total_bytes: number
    used_bytes: number
    free_bytes: number
    used_percent: number
    state: 'healthy' | 'warning' | 'critical'
    cleanup?: StorageCleanup
  }
  camera_health: CameraHealth[]
}

export interface SystemStatus {
  ffmpeg?: { setts_available?: boolean; ffmpeg_version?: string | null }
  recorders?: Array<{ camera_id: number; state: string }>
  recording_schedule?: { cameras?: Array<{ camera_id: number }> }
  upload?: { enabled: boolean; configured: boolean; active: boolean; provider?: string }
  storage_cleanup?: { last_error?: string | null }
  storage?: { used_percent: number; state: 'healthy' | 'warning' | 'critical' }
}

export const useRuntimeStore = defineStore('runtime', () => {
  const healthSnapshot = ref<HealthSnapshot | null>(null)
  const systemStatus = ref<SystemStatus | null>(null)
  const socketState = ref<RuntimeSocketState>('disconnected')
  const loading = ref(false)
  const statusError = ref(false)

  let socket: WebSocket | null = null
  let reconnectTimer: number | null = null
  let systemTimer: number | null = null
  let fallbackTimer: number | null = null
  let started = false

  const recordingCount = computed(() => (systemStatus.value?.recorders || []).filter((item) => item.state === 'RECORDING').length)
  const cameraCount = computed(() => healthSnapshot.value?.cameras.total ?? systemStatus.value?.recording_schedule?.cameras?.length ?? 0)
  const storageState = computed(() => healthSnapshot.value?.storage.state || systemStatus.value?.storage?.state || 'healthy')
  const systemHealthy = computed(() => Boolean(
    systemStatus.value && !statusError.value && systemStatus.value.ffmpeg?.setts_available !== false && storageState.value !== 'critical',
  ))

  function wsUrl() {
    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${scheme}//${window.location.host}/ws/status`
  }

  async function refreshSystem() {
    try {
      systemStatus.value = (await axios.get<SystemStatus>('/api/system/status')).data
      statusError.value = false
    } catch {
      statusError.value = true
    }
  }

  async function refreshHealth() {
    try {
      healthSnapshot.value = (await axios.get<HealthSnapshot>('/api/health/summary')).data
    } catch {
      // Keep the last valid snapshot; socket/fallback will recover later.
    }
  }

  async function refreshInitial() {
    loading.value = true
    try {
      await Promise.all([refreshSystem(), refreshHealth()])
    } finally {
      loading.value = false
    }
  }

  function closeSocket() {
    if (!socket) return
    const current = socket
    socket = null
    current.onopen = null
    current.onmessage = null
    current.onerror = null
    current.onclose = null
    try { current.close() } catch { /* already closed */ }
  }

  function scheduleReconnect() {
    if (!started || reconnectTimer !== null) return
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      connectSocket()
    }, 2000)
  }

  function connectSocket() {
    closeSocket()
    if (!started) return
    socketState.value = 'connecting'
    const ws = new WebSocket(wsUrl())
    socket = ws

    ws.onopen = () => {
      if (socket === ws) socketState.value = 'connected'
    }
    ws.onmessage = (event: MessageEvent) => {
      if (socket !== ws || typeof event.data !== 'string') return
      try {
        const message = JSON.parse(event.data) as { type?: string; data?: HealthSnapshot }
        if (message.type === 'health.snapshot' && message.data) healthSnapshot.value = message.data
      } catch {
        // Ignore unknown status frames.
      }
    }
    ws.onerror = () => {
      if (socket === ws) socketState.value = 'disconnected'
    }
    ws.onclose = () => {
      if (socket !== ws) return
      socket = null
      socketState.value = 'disconnected'
      scheduleReconnect()
    }
  }

  async function refreshFallback() {
    if (socketState.value === 'connected') return
    await refreshHealth()
  }

  function start() {
    if (started) return
    started = true
    void refreshInitial()
    connectSocket()
    systemTimer = window.setInterval(() => void refreshSystem(), 30_000)
    fallbackTimer = window.setInterval(() => void refreshFallback(), 10_000)
  }

  function stop() {
    started = false
    closeSocket()
    socketState.value = 'disconnected'
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
    if (systemTimer !== null) window.clearInterval(systemTimer)
    if (fallbackTimer !== null) window.clearInterval(fallbackTimer)
    reconnectTimer = null
    systemTimer = null
    fallbackTimer = null
  }

  return {
    healthSnapshot,
    systemStatus,
    socketState,
    loading,
    statusError,
    recordingCount,
    cameraCount,
    storageState,
    systemHealthy,
    refreshSystem,
    refreshHealth,
    refreshInitial,
    start,
    stop,
  }
})
