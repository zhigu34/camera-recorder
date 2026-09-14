<script setup lang="ts">
import { onBeforeUnmount, onMounted, watch } from 'vue'

const props = defineProps<{
  active: boolean
  playbackRate: number
  skipSeconds: number
}>()

const emit = defineEmits<{
  skip: [deltaSeconds: number]
  'update:playbackRate': [value: number]
  'update:skipSeconds': [value: number]
}>()

function numericDetail(event: Event) {
  return Number((event as CustomEvent<number>).detail)
}

function handleSkip(event: Event) {
  if (!props.active) return
  const value = numericDetail(event)
  if (Number.isFinite(value)) emit('skip', value)
}

function handleRate(event: Event) {
  const value = numericDetail(event)
  if (Number.isFinite(value)) emit('update:playbackRate', value)
}

function handleInterval(event: Event) {
  const value = numericDetail(event)
  if (Number.isFinite(value)) emit('update:skipSeconds', value)
}

function syncInterval() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent('camera-recorder:playback-interval-sync', { detail: props.skipSeconds }))
}

onMounted(() => {
  window.addEventListener('camera-recorder:playback-skip', handleSkip)
  window.addEventListener('camera-recorder:playback-rate', handleRate)
  window.addEventListener('camera-recorder:playback-interval', handleInterval)
  syncInterval()
})

watch(() => props.skipSeconds, syncInterval)

onBeforeUnmount(() => {
  window.removeEventListener('camera-recorder:playback-skip', handleSkip)
  window.removeEventListener('camera-recorder:playback-rate', handleRate)
  window.removeEventListener('camera-recorder:playback-interval', handleInterval)
})
</script>

<template>
  <span class="playback-transport-bridge" aria-hidden="true"></span>
</template>

<style scoped>
.playback-transport-bridge{display:none}
</style>
