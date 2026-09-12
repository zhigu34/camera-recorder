import axios from 'axios'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export interface SharedCamera {
  id: number
  name: string
  ip: string
  enabled: boolean
  connectivity_status?: 'unknown' | 'online' | 'offline' | string
  recorder_state?: string
  schedule_state?: string
  rtsp_path?: string
  sub_rtsp_path?: string | null
  manufacturer?: string | null
  model?: string | null
  form_factor?: string
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

  function replace(camera: SharedCamera) {
    const index = cameras.value.findIndex((item) => item.id === camera.id)
    if (index >= 0) cameras.value[index] = camera
    else cameras.value.push(camera)
    loadedAt.value = Date.now()
  }

  function remove(cameraId: number) {
    cameras.value = cameras.value.filter((camera) => camera.id !== cameraId)
  }

  return { cameras, loading, byId, enabled, load, invalidate, replace, remove }
})
