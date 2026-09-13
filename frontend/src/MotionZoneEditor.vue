<script setup lang="ts">
import { computed } from 'vue'
import { Delete, RefreshLeft } from '@element-plus/icons-vue'
import {
  canvasPointToNormalized,
  polygonToSvgPoints,
  type NormalizedPoint,
} from './utils/motionZones'

interface ZoneOverlay {
  id: number
  name: string
  enabled: boolean
  polygon: NormalizedPoint[]
}

const props = defineProps<{
  cameraId: number
  modelValue: NormalizedPoint[]
  zones?: ZoneOverlay[]
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: NormalizedPoint[]): void
}>()

const previewSrc = computed(() => `/api/cameras/${props.cameraId}/preview.mjpeg?stream=auto&fps=1&width=960`)
const draftPoints = computed(() => polygonToSvgPoints(props.modelValue))

function addPoint(event: MouseEvent) {
  if (props.modelValue.length >= 24) return
  const target = event.currentTarget
  if (!(target instanceof SVGElement)) return
  const point = canvasPointToNormalized(event.clientX, event.clientY, target.getBoundingClientRect())
  emit('update:modelValue', [...props.modelValue, point])
}

function undo() {
  emit('update:modelValue', props.modelValue.slice(0, -1))
}

function clear() {
  emit('update:modelValue', [])
}
</script>

<template>
  <div class="motion-zone-editor">
    <div class="motion-zone-canvas">
      <img :src="previewSrc" :alt="`摄像头 ${cameraId} 检测区域背景`" />
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" @click="addPoint">
        <polygon
          v-for="zone in zones || []"
          :key="zone.id"
          :points="polygonToSvgPoints(zone.polygon)"
          class="saved-zone"
          :class="{ disabled: !zone.enabled }"
        />
        <polyline v-if="modelValue.length >= 2" :points="draftPoints" class="draft-line" />
        <polygon v-if="modelValue.length >= 3" :points="draftPoints" class="draft-zone" />
        <circle
          v-for="(point, index) in modelValue"
          :key="index"
          :cx="point[0] * 100"
          :cy="point[1] * 100"
          r="1.15"
          class="draft-point"
        />
      </svg>
      <div v-if="!modelValue.length" class="editor-hint">在画面上依次点击至少 3 个点</div>
    </div>
    <div class="editor-actions">
      <span>{{ modelValue.length }} 个顶点 · 最多 24 个</span>
      <div>
        <el-button size="small" :icon="RefreshLeft" :disabled="!modelValue.length" @click="undo">撤销一点</el-button>
        <el-button size="small" :icon="Delete" :disabled="!modelValue.length" @click="clear">清空</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.motion-zone-editor{display:flex;flex-direction:column;gap:8px}.motion-zone-canvas{position:relative;overflow:hidden;min-height:180px;border:1px solid var(--nvr-border);border-radius:9px;background:#05080c}.motion-zone-canvas img{display:block;width:100%;min-height:180px;object-fit:contain;background:#05080c}.motion-zone-canvas svg{position:absolute;inset:0;width:100%;height:100%;cursor:crosshair}.saved-zone{fill:color-mix(in srgb,var(--nvr-blue) 12%,transparent);stroke:color-mix(in srgb,var(--nvr-blue) 74%,transparent);stroke-width:.45;vector-effect:non-scaling-stroke}.saved-zone.disabled{fill:rgba(125,137,153,.05);stroke:rgba(125,137,153,.35);stroke-dasharray:2 2}.draft-zone{fill:color-mix(in srgb,var(--nvr-blue) 20%,transparent);stroke:var(--nvr-blue);stroke-width:.65;vector-effect:non-scaling-stroke}.draft-line{fill:none;stroke:var(--nvr-blue);stroke-width:.65;vector-effect:non-scaling-stroke}.draft-point{fill:#fff;stroke:var(--nvr-blue);stroke-width:.55;vector-effect:non-scaling-stroke}.editor-hint{position:absolute;left:50%;bottom:12px;transform:translateX(-50%);padding:5px 9px;border:1px solid rgba(255,255,255,.1);border-radius:6px;color:#c7d0db;background:rgba(5,8,12,.78);font-size:10px;pointer-events:none}.editor-actions{display:flex;align-items:center;justify-content:space-between;gap:8px;color:var(--nvr-muted);font-size:10px}.editor-actions>div{display:flex;gap:6px}
</style>
