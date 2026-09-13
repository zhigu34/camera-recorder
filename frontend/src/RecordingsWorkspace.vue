<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'

import PlaybackWorkspace from './PlaybackWorkspace.vue'
import RecordingExportHistoryDrawer from './RecordingExportHistoryDrawer.vue'
import RecordingManagementView from './RecordingManagementView.vue'
import { useCameraStore } from './stores/cameras'
import { recordingModeFromMeta, recordingTabLocation } from './utils/recordingsWorkspace'

const route = useRoute()
const router = useRouter()
const cameraStore = useCameraStore()
const { cameras } = storeToRefs(cameraStore)
const mode = computed(() => recordingModeFromMeta(route.meta.recordingMode))
const exportHistoryVisible = ref(false)
const routeCameraId = computed(() => {
  const raw = Array.isArray(route.query.camera_id) ? route.query.camera_id[0] : route.query.camera_id
  const value = Number(raw || 0)
  return Number.isInteger(value) && value > 0 ? value : null
})
const selectedCameraId = computed(() => routeCameraId.value || cameras.value[0]?.id || null)
const selectedCameraName = computed(() => cameras.value.find((camera) => camera.id === selectedCameraId.value)?.name)
const selectedDate = computed(() => {
  const raw = Array.isArray(route.query.date) ? route.query.date[0] : route.query.date
  return typeof raw === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : undefined
})

function switchMode(next: 'playback' | 'manage') {
  if (next === mode.value) return
  void router.push(recordingTabLocation(next, route.query, route.hash))
}

onMounted(() => void cameraStore.load())
</script>

<template>
  <section class="recordings-workspace">
    <nav class="recordings-tabs" aria-label="录像工作区">
      <button type="button" class="recordings-tab" :class="{ active: mode === 'playback' }" @click="switchMode('playback')">回放</button>
      <button type="button" class="recordings-tab" :class="{ active: mode === 'manage' }" @click="switchMode('manage')">录像管理</button>
      <div v-if="mode === 'manage'" class="recordings-tabs-actions">
        <button type="button" class="recordings-export-button" :disabled="!selectedCameraId" @click="exportHistoryVisible = true">
          导出记录
        </button>
      </div>
    </nav>

    <PlaybackWorkspace v-if="mode === 'playback'" />
    <template v-else>
      <RecordingManagementView />
      <RecordingExportHistoryDrawer
        v-model="exportHistoryVisible"
        :camera-id="selectedCameraId"
        :camera-name="selectedCameraName"
        :date="selectedDate"
      />
    </template>
  </section>
</template>

<style scoped>
.recordings-workspace{min-width:0}.recordings-tabs{height:43px;display:flex;align-items:flex-end;gap:18px;padding:0 18px;border-bottom:1px solid var(--nvr-border);background:var(--nvr-topbar)}.recordings-tab{height:43px;padding:0 2px;border:0;border-bottom:2px solid transparent;color:var(--nvr-muted);background:transparent;font:inherit;font-size:11px;font-weight:600;cursor:pointer}.recordings-tab:hover{color:var(--nvr-text-soft)}.recordings-tab.active{color:var(--nvr-text);border-bottom-color:var(--nvr-blue)}.recordings-tabs-actions{height:43px;margin-left:auto;display:flex;align-items:center}.recordings-export-button{height:27px;padding:0 10px;border:1px solid var(--nvr-border);border-radius:6px;background:var(--nvr-input);color:var(--nvr-text-soft);font:inherit;font-size:9px;font-weight:600;cursor:pointer}.recordings-export-button:hover:not(:disabled){border-color:color-mix(in srgb,var(--nvr-blue) 52%,var(--nvr-border));background:color-mix(in srgb,var(--nvr-blue) 8%,var(--nvr-input))}.recordings-export-button:disabled{opacity:.45;cursor:not-allowed}
</style>
