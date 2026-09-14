<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { usePlaybackTransportStore } from './stores/playbackTransport'
import { loadSkipInterval, PLAYBACK_RATES, SKIP_INTERVALS } from './utils/playbackTransport'

const props = defineProps<{
  active: boolean
  playing: boolean
  playbackRate: number
  skipSeconds: number
  muted: boolean
  volume: number
}>()

const emit = defineEmits<{
  'toggle-play': []
  skip: [deltaSeconds: number]
  'update:playbackRate': [value: number]
  'update:skipSeconds': [value: number]
  'update:muted': [value: boolean]
  'update:volume': [value: number]
  fullscreen: []
}>()

function playbackStorage() {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

const transportStore = usePlaybackTransportStore()
const rootRef = ref<HTMLElement | null>(null)
const controlsVisible = ref(true)
const effectiveSkipSeconds = ref(loadSkipInterval(playbackStorage()))
let hideTimer: number | null = null
let interactionHost: HTMLElement | null = null

function clearHideTimer() {
  if (hideTimer !== null) window.clearTimeout(hideTimer)
  hideTimer = null
}

function scheduleHide() {
  clearHideTimer()
  if (!props.playing) {
    controlsVisible.value = true
    return
  }
  hideTimer = window.setTimeout(() => {
    controlsVisible.value = false
  }, 1800)
}

function showControls() {
  controlsVisible.value = true
  scheduleHide()
}

function onSkip(deltaSeconds: number) {
  emit('skip', deltaSeconds)
  transportStore.requestSkip(deltaSeconds)
  showControls()
}

function onRate(event: Event) {
  const value = Number((event.target as HTMLSelectElement).value)
  emit('update:playbackRate', value)
  transportStore.requestRate(value)
  showControls()
}

function onSkipInterval(event: Event) {
  const value = Number((event.target as HTMLSelectElement).value)
  effectiveSkipSeconds.value = value
  emit('update:skipSeconds', value)
  transportStore.requestInterval(value)
  showControls()
}

function onVolume(event: Event) {
  emit('update:volume', Number((event.target as HTMLInputElement).value))
  showControls()
}

watch(() => props.playing, () => {
  controlsVisible.value = true
  scheduleHide()
})
watch(() => props.skipSeconds, (value) => {
  if (SKIP_INTERVALS.includes(value as (typeof SKIP_INTERVALS)[number])) effectiveSkipSeconds.value = value
})

onMounted(() => {
  interactionHost = rootRef.value?.parentElement || null
  interactionHost?.addEventListener('pointermove', showControls)
  interactionHost?.addEventListener('pointerenter', showControls)
})
onBeforeUnmount(() => {
  clearHideTimer()
  interactionHost?.removeEventListener('pointermove', showControls)
  interactionHost?.removeEventListener('pointerenter', showControls)
  interactionHost = null
})
</script>

<template>
  <div
    ref="rootRef"
    class="playback-media-controls"
    :class="{ visible: controlsVisible || !playing }"
    aria-label="回放媒体控制"
    @focusin="showControls"
  >
    <div class="media-controls-scrim"></div>
    <div class="media-controls-row">
      <button
        type="button"
        class="media-icon-button media-primary-button"
        :disabled="!active"
        :aria-label="playing ? '暂停' : '播放'"
        :title="playing ? '暂停' : '播放'"
        @click="emit('toggle-play'); showControls()"
      >
        <svg v-if="playing" viewBox="0 0 24 24" aria-hidden="true">
          <rect x="7" y="5.5" width="3.2" height="13" rx="1" />
          <rect x="13.8" y="5.5" width="3.2" height="13" rx="1" />
        </svg>
        <svg v-else viewBox="0 0 24 24" aria-hidden="true">
          <path d="M8 5.8v12.4L18 12 8 5.8Z" />
        </svg>
      </button>

      <button
        type="button"
        class="media-icon-button media-skip-button"
        :disabled="!active"
        :aria-label="`倒退 ${effectiveSkipSeconds} 秒`"
        :title="`倒退 ${effectiveSkipSeconds} 秒`"
        @click="onSkip(-effectiveSkipSeconds)"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4.5 5v4h4" />
          <path d="M5 8.2A8 8 0 1 1 4.9 16.4" />
        </svg>
        <span>{{ effectiveSkipSeconds }}</span>
      </button>

      <button
        type="button"
        class="media-icon-button media-skip-button"
        :disabled="!active"
        :aria-label="`快进 ${effectiveSkipSeconds} 秒`"
        :title="`快进 ${effectiveSkipSeconds} 秒`"
        @click="onSkip(effectiveSkipSeconds)"
      >
        <svg class="media-forward-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4.5 5v4h4" />
          <path d="M5 8.2A8 8 0 1 1 4.9 16.4" />
        </svg>
        <span>{{ effectiveSkipSeconds }}</span>
      </button>

      <div class="media-controls-spacer"></div>

      <button
        type="button"
        class="media-icon-button"
        :aria-label="muted ? '取消静音' : '静音'"
        :title="muted ? '取消静音' : '静音'"
        @click="emit('update:muted', !muted); showControls()"
      >
        <svg v-if="muted || volume <= 0" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4.5 10h3l4-3.3v10.6L7.5 14h-3Z" />
          <path d="m15.5 9 4 6m0-6-4 6" />
        </svg>
        <svg v-else viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4.5 10h3l4-3.3v10.6L7.5 14h-3Z" />
          <path d="M15 9.3a4 4 0 0 1 0 5.4" />
          <path d="M17.5 7a7 7 0 0 1 0 10" />
        </svg>
      </button>

      <input
        class="media-volume"
        type="range"
        min="0"
        max="1"
        step="0.05"
        :value="volume"
        aria-label="音量"
        @input="onVolume"
      />

      <label class="media-select-pill">
        <span class="sr-only">播放倍速</span>
        <select :value="playbackRate" aria-label="播放倍速" @change="onRate">
          <option v-for="rate in PLAYBACK_RATES" :key="rate" :value="rate">{{ rate }}×</option>
        </select>
      </label>

      <label class="media-select-pill media-skip-select">
        <span class="sr-only">跳转间隔</span>
        <select :value="effectiveSkipSeconds" aria-label="跳转间隔" @change="onSkipInterval">
          <option v-for="seconds in SKIP_INTERVALS" :key="seconds" :value="seconds">{{ seconds }}s</option>
        </select>
      </label>

      <button
        type="button"
        class="media-icon-button"
        aria-label="全屏"
        title="全屏"
        @click="emit('fullscreen'); showControls()"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M8.5 4.5h-4v4M15.5 4.5h4v4M8.5 19.5h-4v-4M19.5 15.5v4h-4" />
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.playback-media-controls{position:absolute;inset:0;z-index:8;pointer-events:none;opacity:0;transition:opacity .16s ease}.playback-media-controls.visible{opacity:1}.media-controls-scrim{position:absolute;inset:45% 0 0;background:linear-gradient(180deg,transparent,rgba(0,0,0,.58) 74%,rgba(0,0,0,.76))}.media-controls-row{position:absolute;left:12px;right:12px;bottom:10px;display:flex;align-items:center;gap:3px;pointer-events:auto}.playback-media-controls:not(.visible) .media-controls-row{pointer-events:none}.media-controls-spacer{flex:1}.media-icon-button{position:relative;width:32px;height:32px;display:grid;place-items:center;padding:0;border:0;border-radius:7px;background:transparent;color:rgba(241,247,252,.78);cursor:pointer;transition:background .12s ease,color .12s ease,opacity .12s ease}.media-icon-button:hover:not(:disabled),.media-icon-button:focus-visible{color:#fff;background:rgba(255,255,255,.11)}.media-icon-button:disabled{opacity:.32;cursor:default}.media-icon-button svg{width:19px;height:19px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}.media-primary-button svg{fill:currentColor;stroke:none}.media-skip-button svg{width:24px;height:24px}.media-skip-button span{position:absolute;inset:0;display:grid;place-items:center;padding-top:1px;font-size:7px;font-weight:700;font-variant-numeric:tabular-nums}.media-forward-icon{transform:scaleX(-1)}.media-volume{width:72px;height:20px;accent-color:#fff;cursor:pointer}.media-select-pill{position:relative;display:inline-flex;align-items:center}.media-select-pill::after{content:'';position:absolute;right:8px;top:50%;width:4px;height:4px;border-right:1px solid rgba(255,255,255,.6);border-bottom:1px solid rgba(255,255,255,.6);transform:translateY(-65%) rotate(45deg);pointer-events:none}.media-select-pill select{height:28px;min-width:55px;appearance:none;padding:0 20px 0 9px;border:0;border-radius:7px;background:rgba(8,13,19,.7);color:rgba(241,247,252,.84);font:inherit;font-size:9px;font-weight:650;cursor:pointer;backdrop-filter:blur(8px)}.media-skip-select select{min-width:57px}.media-select-pill select:hover,.media-select-pill select:focus-visible{background:rgba(255,255,255,.12);color:#fff}.media-icon-button:focus-visible,.media-select-pill select:focus-visible,.media-volume:focus-visible{outline:2px solid rgba(76,141,255,.88);outline-offset:1px}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@media(max-width:700px){.media-controls-row{left:7px;right:7px;bottom:7px;gap:1px}.media-volume{display:none}.media-icon-button{width:30px;height:30px}.media-select-pill select{height:27px;min-width:50px;padding-left:7px;padding-right:18px;font-size:8px}.media-skip-select{display:none}}
</style>