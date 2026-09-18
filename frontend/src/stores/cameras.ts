import axios from 'axios'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { CameraConnectionRead } from '../camera-editor/types'

export interface RecordingWindow {
  days: number[]
  start: string
  end: string
}

export interface SharedCamera {
  id: number
  name: string
  manufacturer?: string | null
  model?: string | null
  form_factor?: string
  ip: string
  rtsp_port?: number
  username?: string
  rtsp_path?: string
  sub_rtsp_path?: string | null
  enabled: boolean
  auto_record?: boolean
  recording_schedule_enabled?: boolean
  recording_schedule?: RecordingWindow[]
  timestamp_mode?: 'native' | 'reconstruct' | 'wallclock' | string
  password_set?: boolean
  connection?: CameraConnectionRead | null
  video_codec?: string | null
  video_profile?: string | null
  width?: number | null
  height?: number | null
  fps_num?: number | null
  fps_den?: number | null
  pixel_format?: string | null
  has_b_frames?: number | null
  video_time_base?: string | null
  audio_codec?: string | null
  audio_profile?: string | null
  sample_rate?: number | null
  channels?: number | null
  audio_frame_samples?: number | null
  status?: string
  connectivity_status?: 'unknown' | 'online' | 'offline' | string
  recorder_state?: string
  schedule_state?: string
  last_probe_at?: string | null
  last_online_at?: string | null
  created_at?: string
  updated_at?: string
}

const FRESH_FOR_MS = 10_000

export const useCameraStore = defineStore('cameras', () => {
  const cameras = ref<SharedCamera[]>([])
  const loading = ref(false)
  const loadedAt = ref(0)
  let pending: Promise<SharedCamera[]> | null = null

  const byId = computed(() => new Map(cameras.value.map((camera) => [camera.id, camera])))
  const enabled = computed(() => cameras.value.filter((camera) => camera.enabled))

  async function load(force = false) {
    if (!force && cameras.value.length && Date.now() - loadedAt.value < FRESH_FOR_MS) return cameras.value
    if (pending) return pending

    loading.value = true
    pending = axios.get<SharedCamera[]>('/api/cameras')
      .then((response) => {
        cameras.value = response.data
        loadedAt.value = Date.now()
        return cameras.value
      })
      .finally(() => {
        loading.value = false
        pending = null
      })
    return pending
  }

  function invalidate() {
    loadedAt.value = 0
  }

  function setAll(items: SharedCamera[]) {
    cameras.value = items
    loadedAt.value = Date.now()
  }

  function replace(camera: SharedCamera) {
    const index = cameras.value.findIndex((item) => item.id === camera.id)
    if (index >= 0) cameras.value[index] = camera
    else cameras.value.push(camera)
    loadedAt.value = Date.now()
  }

  function remove(cameraId: number) {
    cameras.value = cameras.value.filter((camera) => camera.id !== cameraId)
    loadedAt.value = Date.now()
  }

  return { cameras, loading, loadedAt, byId, enabled, load, invalidate, setAll, replace, remove }
})
