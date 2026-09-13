<script setup lang="ts">
import { computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import CamerasWorkspace from './CamerasWorkspace.vue'
import DashboardView from './DashboardView.vue'
import EventCenterView from './EventCenterView.vue'
import HealthView from './HealthView.vue'
import PlaybackMetricsPanel from './PlaybackMetricsPanel.vue'
import PreviewView from './PreviewView.vue'
import RecordingsWorkspace from './RecordingsWorkspace.vue'
import RecordingScheduleView from './RecordingScheduleView.vue'
import SystemSettingsWorkspace from './SystemSettingsWorkspace.vue'
import UploadManagementView from './UploadManagementView.vue'

const route = useRoute()
const router = useRouter()
const renderKey = computed(() => String(route.meta.navKey || 'dashboard'))

function go(path: string) {
  void router.push(path)
}

async function openPlaybackCompatibility() {
  await router.push({ path: '/recordings/manage', hash: '#playback-compatibility' })
  await nextTick()
  document.getElementById('playback-compatibility')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <DashboardView v-if="renderKey === 'dashboard'" />
  <CamerasWorkspace v-else-if="renderKey === 'cameras'" @open-preview="go('/preview')" />
  <RecordingsWorkspace v-else-if="renderKey === 'recordings'" />
  <UploadManagementView v-else-if="renderKey === 'uploads'" @open-settings="go('/settings')" @open-recordings="go('/recordings/manage')" />
  <EventCenterView v-else-if="renderKey === 'events'" @open-cameras="go('/cameras')" @open-recordings="go('/recordings/playback')" @open-uploads="go('/uploads')" @open-health="go('/health-center')" />
  <PreviewView v-else-if="renderKey === 'preview'" />
  <RecordingScheduleView v-else-if="renderKey === 'schedule'" />
  <template v-else-if="renderKey === 'health'">
    <HealthView />
    <PlaybackMetricsPanel compact @open-playback="openPlaybackCompatibility" />
  </template>
  <SystemSettingsWorkspace v-else-if="renderKey === 'settings'" @open-events="go('/events')" />
</template>
