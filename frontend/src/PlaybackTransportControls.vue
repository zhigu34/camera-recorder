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
        class="transport-skip-button"
        :disabled="!active"
        :aria-label="`倒退 ${skipSeconds} 秒`"
        :title="`倒退 ${skipSeconds} 秒`"
        @click="emit('skip', -props.skipSeconds)"
      >
        <svg class="transport-skip-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4.3 4.8v4.1h4.1" />
          <path d="M4.9 8.2A8 8 0 1 1 4.8 16.4" />
        </svg>
        <span class="transport-skip-value">{{ skipSeconds }}</span>
      </button>
      <button
        type="button"
        class="transport-skip-button"
        :disabled="!active"
        :aria-label="`快进 ${skipSeconds} 秒`"
        :title="`快进 ${skipSeconds} 秒`"
        @click="emit('skip', props.skipSeconds)"
      >
        <svg class="transport-skip-icon transport-skip-icon-forward" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4.3 4.8v4.1h4.1" />
          <path d="M4.9 8.2A8 8 0 1 1 4.8 16.4" />
        </svg>
        <span class="transport-skip-value">{{ skipSeconds }}</span>
      </button>
    </div>

    <div class="playback-transport-options">
      <label class="transport-pill">
        <span class="transport-sr-only">播放倍速</span>
        <select :value="playbackRate" aria-label="播放倍速" title="播放倍速" @change="updatePlaybackRate">
          <option v-for="rate in PLAYBACK_RATES" :key="rate" :value="rate">{{ rate }}×</option>
        </select>
      </label>

      <label class="transport-pill transport-pill-skip">
        <span class="transport-sr-only">快进倒退秒数</span>
        <select :value="skipSeconds" aria-label="快进倒退秒数" title="快进倒退间隔" @change="updateSkipSeconds">
          <option v-for="seconds in SKIP_INTERVALS" :key="seconds" :value="seconds">{{ seconds }}s</option>
        </select>
      </label>
    </div>
  </div>
</template>

<style scoped>
.playback-transport{min-height:32px;display:flex;align-items:center;justify-content:flex-end;gap:10px;margin-top:5px;padding:2px 0 0}.playback-transport-jump,.playback-transport-options{display:flex;align-items:center}.playback-transport-jump{gap:1px}.playback-transport-options{gap:5px}.transport-skip-button{position:relative;width:32px;height:32px;display:grid;place-items:center;padding:0;border:0;border-radius:7px;background:transparent;color:var(--nvr-subtle);font:inherit;cursor:pointer;transition:background .14s ease,color .14s ease,opacity .14s ease}.transport-skip-button:hover:not(:disabled){background:var(--nvr-hover);color:var(--nvr-text)}.transport-skip-button:active:not(:disabled){background:color-mix(in srgb,var(--nvr-blue) 10%,var(--nvr-hover))}.transport-skip-button:disabled{opacity:.32;cursor:not-allowed}.transport-skip-icon{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:1.55;stroke-linecap:round;stroke-linejoin:round}.transport-skip-icon-forward{transform:scaleX(-1)}.transport-skip-value{position:absolute;inset:0;display:grid;place-items:center;padding-top:1px;color:currentColor;font-size:7px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.03em;pointer-events:none}.transport-pill{position:relative;display:inline-flex;align-items:center}.transport-pill::after{content:'';position:absolute;right:8px;top:50%;width:4px;height:4px;border-right:1px solid var(--nvr-subtle);border-bottom:1px solid var(--nvr-subtle);transform:translateY(-65%) rotate(45deg);pointer-events:none}.transport-pill select{height:27px;min-width:54px;appearance:none;padding:0 19px 0 9px;border:0;border-radius:7px;background:color-mix(in srgb,var(--nvr-input) 76%,transparent);color:var(--nvr-text-soft);font:inherit;font-size:9px;font-weight:600;font-variant-numeric:tabular-nums;cursor:pointer;transition:background .14s ease,color .14s ease}.transport-pill-skip select{min-width:57px}.transport-pill select:hover{background:var(--nvr-hover);color:var(--nvr-text)}.transport-pill select:focus-visible,.transport-skip-button:focus-visible{outline:2px solid color-mix(in srgb,var(--nvr-blue) 60%,transparent);outline-offset:1px}.transport-sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@media(max-width:700px){.playback-transport{justify-content:center;gap:14px;padding-top:4px}.transport-skip-button{width:34px;height:34px}.transport-skip-icon{width:25px;height:25px}}
</style>
