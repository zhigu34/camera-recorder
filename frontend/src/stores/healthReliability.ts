import axios from 'axios'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export type ReliabilityWindow = 24 | 72
export type ReliabilityVerdict = 'pass' | 'fail' | 'collecting' | 'ignored'
export type ReliabilityConfidence = 'high' | 'medium' | 'low'

export interface RecordingGapDiagnostic {
  start_at: string
  end_at: string
  duration_seconds: number
  cause: string
  cause_label: string
  detail: string
  confidence: ReliabilityConfidence
}

export interface ReliabilityIssueAction {
  type: 'camera' | 'events' | 'playback' | 'operations' | string
  camera_id?: number | null
  at?: string | null
}

export interface ReliabilityIssue {
  kind: string
  severity: 'error' | 'warning' | 'info' | string
  camera_id?: number | null
  title: string
  detail: string
  started_at?: string | null
  ended_at?: string | null
  cause: string
  confidence: ReliabilityConfidence | string
  action?: ReliabilityIssueAction | null
}

export interface CameraReliability {
  camera_id: number
  name: string
  ip: string
  monitored: boolean
  verdict: ReliabilityVerdict
  reasons: string[]
  sample_coverage: number
  observed_minutes: number
  recorder_availability_rate: number | null
  recording_completeness: number | null
  recording_segments: number
  complete_segments: number
  recording_gap_count: number
  missing_recording_seconds: number
  unexplained_recording_gaps: number
  gap_cause_counts: Record<string, number>
  diagnostics: RecordingGapDiagnostic[]
  primary_problem?: {
    kind?: string
    cause?: string
    detail?: string
    confidence?: ReliabilityConfidence | string
    started_at?: string | null
    ended_at?: string | null
  } | null
  ffmpeg_failures: number
  failure_streaks: number
  max_consecutive_failures: number
  outage_count: number
  total_offline_seconds: number
  longest_offline_seconds: number
  current_offline_seconds: number
  continuous_failure_active: boolean
}

export interface HealthReliabilityReport {
  generated_at: string
  hours: ReliabilityWindow
  criteria: Record<string, number>
  overall: {
    verdict: Exclude<ReliabilityVerdict, 'ignored'>
    monitored_cameras: number
    passed_cameras: number
    failed_cameras: number
    collecting_cameras: number
    recorder_availability_rate: number | null
    recording_completeness: number | null
    recording_gap_count: number
    missing_recording_seconds: number
    unexplained_recording_gaps: number
    ffmpeg_failures: number
    failure_streaks: number
    outage_count: number
    total_offline_seconds: number
    longest_offline_seconds: number
  }
  issues: ReliabilityIssue[]
  cameras: CameraReliability[]
}

function errorMessage(error: unknown) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    return typeof detail === 'string' && detail ? detail : error.message || '可靠性数据加载失败'
  }
  return error instanceof Error ? error.message : '可靠性数据加载失败'
}

export const useHealthReliabilityStore = defineStore('healthReliability', () => {
  const windowHours = ref<ReliabilityWindow>(24)
  const cache = ref<Partial<Record<ReliabilityWindow, HealthReliabilityReport>>>({})
  const lastLoadedAt = ref<Partial<Record<ReliabilityWindow, string>>>({})
  const loading = ref(false)
  const error = ref('')

  const report = computed(() => cache.value[windowHours.value] ?? null)

  async function refresh(force = false) {
    const hours = windowHours.value
    if (!force && cache.value[hours]) return cache.value[hours] ?? null

    loading.value = true
    error.value = ''
    try {
      const { data } = await axios.get<HealthReliabilityReport>('/api/health/reliability', {
        params: { hours },
      })
      cache.value = { ...cache.value, [hours]: data }
      lastLoadedAt.value = { ...lastLoadedAt.value, [hours]: new Date().toISOString() }
      return data
    } catch (caught) {
      error.value = errorMessage(caught)
      return cache.value[hours] ?? null
    } finally {
      loading.value = false
    }
  }

  async function setWindow(hours: ReliabilityWindow) {
    windowHours.value = hours
    return await refresh(false)
  }

  function clear() {
    cache.value = {}
    lastLoadedAt.value = {}
    error.value = ''
  }

  return {
    windowHours,
    report,
    loading,
    error,
    lastLoadedAt,
    setWindow,
    refresh,
    clear,
  }
})
