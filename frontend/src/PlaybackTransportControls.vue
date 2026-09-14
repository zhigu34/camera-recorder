<script setup lang="ts">
import { watch } from 'vue'
import { storeToRefs } from 'pinia'
import { usePlaybackTransportStore } from './stores/playbackTransport'

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

const transportStore = usePlaybackTransportStore()
const { command } = storeToRefs(transportStore)

watch(command, (next) => {
  if (!next || !Number.isFinite(next.value)) return
  if (next.type === 'skip') {
    if (props.active) emit('skip', next.value)
    return
  }
  if (next.type === 'rate') {
    emit('update:playbackRate', next.value)
    return
  }
  emit('update:skipSeconds', next.value)
}, { flush: 'sync' })
</script>

<template>
  <span class="playback-transport-bridge" aria-hidden="true"></span>
</template>

<style scoped>
.playback-transport-bridge{display:none}
</style>
