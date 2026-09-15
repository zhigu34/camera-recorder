<script setup lang="ts">
import { computed, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const CamerasWorkspace = defineAsyncComponent(() => import('./CamerasWorkspace.vue'))
const DashboardView = defineAsyncComponent(() => import('./DashboardView.vue'))
const EventCenterView = defineAsyncComponent(() => import('./EventCenterView.vue'))
const HealthCenterView = defineAsyncComponent(() => import('./HealthCenterView.vue'))
const PreviewView = defineAsyncComponent(() => import('./PreviewView.vue'))
const RecordingsWorkspace = defineAsyncComponent(() => import('./RecordingsWorkspace.vue'))
const RecordingScheduleView = defineAsyncComponent(() => import('./RecordingScheduleView.vue'))
const SystemSettingsWorkspace = defineAsyncComponent(() => import('./SystemSettingsWorkspace.vue'))
const UploadManagementView = defineAsyncComponent(() => import('./UploadManagementView.vue'))

const route = useRoute()
const router = useRouter()
const renderKey = computed(() => String(route.meta.navKey || 'dashboard'))

function go(path: string) {
  void router.push(path)
}
</script>

<template>
  <DashboardView v-if="renderKey === 'dashboard'" />
  <CamerasWorkspace v-else-if="renderKey === 'cameras'" @open-preview="go('/preview')" />
  <RecordingsWorkspace v-else-if="renderKey === 'recordings'" />
  <UploadManagementView v-else-if="renderKey === 'uploads'" @open-settings="go('/settings?section=archive')" @open-recordings="go('/recordings/manage')" />
  <EventCenterView v-else-if="renderKey === 'events'" @open-cameras="go('/cameras')" @open-recordings="go('/recordings/playback')" @open-uploads="go('/uploads')" @open-health="go('/health-center')" />
  <PreviewView v-else-if="renderKey === 'preview'" />
  <RecordingScheduleView v-else-if="renderKey === 'schedule'" />
  <HealthCenterView v-else-if="renderKey === 'health'" />
  <SystemSettingsWorkspace v-else-if="renderKey === 'settings'" @open-events="go('/events')" />
</template>
