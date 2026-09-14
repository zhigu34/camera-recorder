<script setup lang="ts">
import { PLAYBACK_RATES, SKIP_INTERVALS } from './utils/playbackTransport'

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

function updatePlaybackRate(event: Event) {
  emit('update:playbackRate', Number((event.target as HTMLSelectElement).value))
}

function updateSkipSeconds(event: Event) {
  emit('update:skipSeconds', Number((event.target as HTMLSelectElement).value))
}
</script>

<template>
  <div class="playback-transport" aria-label="回放控制">
    <div class="playback-transport-jump">
      <button
        type="button"
        class="transport-button"
        :disabled="!active"
        :aria-label="`倒退 ${skipSeconds} 秒`"
        @click="emit('skip', -props.skipSeconds)"
      >
        <span class="transport-arrow">↶</span>
        <span>{{ skipSeconds }}s</span>
      </button>
      <button
        type="button"
        class="transport-button"
        :disabled="!active"
        :aria-label="`快进 ${skipSeconds} 秒`"
        @click="emit('skip', props.skipSeconds)"
      >
        <span>{{ skipSeconds }}s</span>
        <span class="transport-arrow">↷</span>
      </button>
    </div>

    <label class="transport-select">
      <span>倍速</span>
      <select :value="playbackRate" aria-label="播放倍速" @change="updatePlaybackRate">
        <option v-for="rate in PLAYBACK_RATES" :key="rate" :value="rate">{{ rate }}×</option>
      </select>
    </label>

    <label class="transport-select">
      <span>跳转</span>
      <select :value="skipSeconds" aria-label="快进倒退秒数" @change="updateSkipSeconds">
        <option v-for="seconds in SKIP_INTERVALS" :key="seconds" :value="seconds">{{ seconds }} 秒</option>
      </select>
    </label>
  </div>
</template>

<style scoped>
.playback-transport{min-height:34px;display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:7px 2px 0;border-top:1px solid color-mix(in srgb,var(--nvr-border) 72%,transparent);margin-top:8px}.playback-transport-jump{display:flex;gap:5px}.transport-button{height:27px;min-width:58px;display:inline-flex;align-items:center;justify-content:center;gap:4px;padding:0 8px;border:1px solid var(--nvr-border);border-radius:6px;background:var(--nvr-input);color:var(--nvr-text-soft);font:inherit;font-size:9px;font-weight:600;cursor:pointer}.transport-button:hover:not(:disabled){border-color:color-mix(in srgb,var(--nvr-blue) 52%,var(--nvr-border));background:color-mix(in srgb,var(--nvr-blue) 8%,var(--nvr-input));color:var(--nvr-text)}.transport-button:disabled{opacity:.42;cursor:not-allowed}.transport-arrow{font-size:14px;line-height:1}.transport-select{display:flex;align-items:center;gap:5px;color:var(--nvr-subtle);font-size:8px}.transport-select select{height:27px;padding:0 22px 0 7px;border:1px solid var(--nvr-border);border-radius:6px;background:var(--nvr-input);color:var(--nvr-text-soft);font:inherit;font-size:9px;cursor:pointer}.transport-select select:focus-visible,.transport-button:focus-visible{outline:2px solid color-mix(in srgb,var(--nvr-blue) 62%,transparent);outline-offset:1px}@media(max-width:700px){.playback-transport{justify-content:space-between;flex-wrap:wrap}.playback-transport-jump{flex:1}.transport-button{flex:1}.transport-select{flex:1;justify-content:flex-end}}
</style>
