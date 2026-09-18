<script setup lang="ts">
import { ref, watch } from 'vue'
import axios from 'axios'
import { useRouter } from 'vue-router'

import type { CameraDeletionImpact } from './camera-management/types'
import {
  cameraActivityRoute,
  cameraHealthRoute,
  cameraRecordingsRoute,
  cameraSystemEventsRoute,
  cameraUploadsRoute,
} from './navigation'

const props = defineProps<{ cameraId: number }>()

const router = useRouter()
const loading = ref(false)
const error = ref('')
const impact = ref<CameraDeletionImpact | null>(null)
let requestId = 0

async function load() {
  const id = props.cameraId
  const current = ++requestId
  loading.value = true
  error.value = ''
  try {
    const response = await axios.get<CameraDeletionImpact>(`/api/cameras/${id}/deletion-impact`)
    if (current === requestId) impact.value = response.data
  } catch {
    if (current === requestId) {
      impact.value = null
      error.value = '历史摘要暂不可用'
    }
  } finally {
    if (current === requestId) loading.value = false
  }
}

watch(() => props.cameraId, () => void load(), { immediate: true })
</script>

<template>
  <section class="camera-history-panel" aria-label="摄像头历史摘要">
    <div class="camera-history-heading">
      <div>
        <span>HISTORY</span>
        <strong>历史与关联数据</strong>
      </div>
      <small v-if="loading">读取中…</small>
      <small v-else-if="error">{{ error }}</small>
      <button v-else type="button" @click="load">刷新</button>
    </div>

    <div class="camera-history-grid">
      <button type="button" @click="router.push(cameraRecordingsRoute(cameraId))">
        <span>录像</span>
        <strong>{{ impact?.recordings ?? '—' }}</strong>
        <small>查看录像管理</small>
      </button>
      <button type="button" @click="router.push(cameraActivityRoute(cameraId))">
        <span>移动活动</span>
        <strong>{{ impact?.motion_events ?? '—' }}</strong>
        <small>查看活动</small>
      </button>
      <button type="button" @click="router.push(cameraActivityRoute(cameraId))">
        <span>原生检测</span>
        <strong>{{ impact?.detection_events ?? '—' }}</strong>
        <small>查看活动</small>
      </button>
      <button type="button" @click="router.push(cameraSystemEventsRoute(cameraId))">
        <span>阻塞事件</span>
        <strong>{{ impact?.blocking_events ?? '—' }}</strong>
        <small>查看系统事件</small>
      </button>
      <button type="button" @click="router.push(cameraHealthRoute(cameraId))">
        <span>健康样本</span>
        <strong>{{ impact?.health_samples ?? '—' }}</strong>
        <small>查看健康中心</small>
      </button>
      <button type="button" @click="router.push(cameraUploadsRoute(cameraId))">
        <span>待处理上传</span>
        <strong>{{ impact?.pending_uploads ?? '—' }}</strong>
        <small>查看上传管理</small>
      </button>
    </div>
  </section>
</template>
