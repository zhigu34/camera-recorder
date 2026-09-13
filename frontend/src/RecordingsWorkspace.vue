<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import PlaybackWorkspace from './PlaybackWorkspace.vue'
import RecordingManagementView from './RecordingManagementView.vue'
import { recordingModeFromMeta, recordingTabLocation } from './utils/recordingsWorkspace'

const route = useRoute()
const router = useRouter()
const mode = computed(() => recordingModeFromMeta(route.meta.recordingMode))

function switchMode(next: 'playback' | 'manage') {
  if (next === mode.value) return
  void router.push(recordingTabLocation(next, route.query, route.hash))
}
</script>

<template>
  <section class="recordings-workspace">
    <nav class="recordings-tabs" aria-label="录像工作区">
      <button type="button" :class="{ active: mode === 'playback' }" @click="switchMode('playback')">回放</button>
      <button type="button" :class="{ active: mode === 'manage' }" @click="switchMode('manage')">录像管理</button>
    </nav>

    <PlaybackWorkspace v-if="mode === 'playback'" />
    <RecordingManagementView v-else />
  </section>
</template>

<style scoped>
.recordings-workspace{min-width:0}.recordings-tabs{height:43px;display:flex;align-items:flex-end;gap:18px;padding:0 18px;border-bottom:1px solid var(--nvr-border);background:var(--nvr-topbar)}.recordings-tabs button{height:43px;padding:0 2px;border:0;border-bottom:2px solid transparent;color:var(--nvr-muted);background:transparent;font:inherit;font-size:11px;font-weight:600;cursor:pointer}.recordings-tabs button:hover{color:var(--nvr-text-soft)}.recordings-tabs button.active{color:var(--nvr-text);border-bottom-color:var(--nvr-blue)}
</style>
