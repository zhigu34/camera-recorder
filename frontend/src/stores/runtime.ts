import axios from 'axios'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export type RuntimeSocketState = 'connecting' | 'connected' | 'disconnected'

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
  connectivity_source?: string | null
  connectivity_failures?: number
  recorder_state: string
  schedule_state: string
  state?: string
  abnormal: boolean
  restart_count: number
  warning_count?: number
  network_warning_count?: number
  timestamp_mode?: string
  timestamp_warning_count?: number
  timestamp_guidance?: TimestampGuidance | null
  pid?: number | null
  started_at?: string | null
  offline_since?: string | null
  current_offline_seconds?: number
  last_error?: string | null
}

export interface RealtimeHealthSnapshot {
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
  storage: {
    total_bytes: number
    free_bytes: number
    used_percent: number
    state: 'healthy' | 'warning' | 'critical'
  }
  upload: {
    enabled: boolean
    configured: boolean
    active: boolean
  }
  connectivity_monitor?: {
    running?: boolean
    last_cycle_at?: string | null
    error_count?: number
    last_error?: string | null
  }
  camera_health: CameraHealth[]
}

export interface RecorderRuntime {
  camera_id: number
  state: string
  pid?: number | null
  restart_count?: number
  warning_count?: number
  timestamp_warning_count?: number
  network_warning_count?: number
  last_error?: string | null
}

export interface ScheduleRuntime {
  camera_id: number
  schedule_enabled?: boolean
  schedule?: string
  schedule_state?: string
  in_window?: boolean
  auto_eligible?: boolean
  running?: boolean
  mode?: string
}

export interface SystemStatus {
  ffmpeg?: { setts_available?: boolean; ffmpeg_version?: string | null }
  recorders?: RecorderRuntime[]
  recording_schedule?: {
    running?: boolean
    poll_interval_seconds?: number
    last_check_at?: string | null
    last_error?: string | null
    cameras?: ScheduleRuntime[]
  }
  connectivity_monitor?: {
    running?: boolean
    last_cycle_at?: string | null
    error_count?: number
    last_error?: string | null
  }
  upload?: {
    enabled: boolean
    configured: boolean
    active: boolean
    provider?: string
    local_retention_hours?: number
  }
  storage_cleanup?: { last_error?: string | null }
  storage?: { used_percent: number; state: 'healthy' | 'warning' | 'critical' }
}

export const useRuntimeStore = defineStore('runtime', () => {
  const healthSnapshot = ref<RealtimeHealthSnapshot | null>(null)
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

  function recorderState(cameraId: number | null | undefined) {
    if (!cameraId) return 'STOPPED'
    const health = healthSnapshot.value?.camera_health.find((item) => item.camera_id === cameraId)
    if (health?.recorder_state) return health.recorder_state
    return systemStatus.value?.recorders?.find((item) => item.camera_id === cameraId)?.state || 'STOPPED'
  }

  function scheduleRuntime(cameraId: number | null | undefined) {
    if (!cameraId) return undefined
    return systemStatus.value?.recording_schedule?.cameras?.find((item) => item.camera_id === cameraId)
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
      healthSnapshot.value = (await axios.get<RealtimeHealthSnapshot>('/api/health/realtime')).data
    } catch {
      // Keep the last valid realtime snapshot; websocket/fallback will recover later.
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
        const message = JSON.parse(event.data) as { type?: string; data?: RealtimeHealthSnapshot }
        if (message.type === 'health.realtime' && message.data) healthSnapshot.value = message.data
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
    systemTimer = window.setInterval(() => void refreshSystem(), 10_000)
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
    recorderState,
    scheduleRuntime,
    refreshSystem,
    refreshHealth,
    refreshInitial,
    start,
    stop,
  }
})
