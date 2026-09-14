<script setup lang="ts">
import { computed, markRaw, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import {
  Clock,
  Close,
  FullScreen,
  MoreFilled,
  Setting,
  VideoCamera,
  VideoPause,
  VideoPlay,
} from '@element-plus/icons-vue'

import { useCameraStore } from './stores/cameras'
import { useRuntimeStore } from './stores/runtime'
import {
  isActiveTileState,
  shouldResumeAfterVisibility,
  tilePrimaryAction,
  tilePrimaryLabel,
  type PreviewTileState,
} from './utils/previewTileState'

type LayoutCount = 1 | 4 | 9
type PreviewStream = 'auto' | 'sub' | 'main'
type ActivePreviewStream = 'sub' | 'main'

interface WallSlot {
  cameraId: number | null
  stream: PreviewStream
  activeStream: ActivePreviewStream | null
  frameUrl: string
  loaded: boolean
  failed: boolean
  error: string
  state: PreviewTileState
  startedByUser: boolean
  resumeAfterVisibility: boolean
  socket: WebSocket | null
  socketGeneration: number
  reconnectTimer: number | null
}

interface SavedWall {
  layout?: LayoutCount
  slots?: Array<{ cameraId: number | null; stream: PreviewStream }>
}

const STORAGE_KEY = 'nvr-video-wall-v1'
const router = useRouter()
const cameraStore = useCameraStore()
const runtimeStore = useRuntimeStore()
const { cameras } = storeToRefs(cameraStore)
const loading = ref(false)
const layoutCount = ref<LayoutCount>(4)
const draggingCameraId = ref<number | null>(null)
let mounted = false

function emptySlot(cameraId: number | null = null, stream: PreviewStream = 'auto'): WallSlot {
  return {
    cameraId,
    stream,
    activeStream: null,
    frameUrl: '',
    loaded: false,
    failed: false,
    error: '',
    state: 'idle',
    startedByUser: false,
    resumeAfterVisibility: false,
    socket: null,
    socketGeneration: 0,
    reconnectTimer: null,
  }
}

const slots = ref<WallSlot[]>(Array.from({ length: 9 }, () => emptySlot()))
const activeSlots = computed(() => slots.value.slice(0, layoutCount.value))
const enabledCameras = computed(() => cameras.value.filter((camera) => camera.enabled))
const assignedIds = computed(() => new Set(activeSlots.value.map((slot) => slot.cameraId).filter((id): id is number => id !== null)))
const playingCount = computed(() => activeSlots.value.filter((slot) => isActiveTileState(slot.state)).length)
const configuredCount = computed(() => activeSlots.value.filter((slot) => slot.cameraId !== null).length)

const previewProfile = computed(() => {
  if (layoutCount.value === 1) return { fps: 8, width: 1280, label: '8fps · 1280px' }
  if (layoutCount.value === 4) return { fps: 5, width: 640, label: '5fps · 640px' }
  return { fps: 3, width: 480, label: '3fps · 480px' }
})

function cameraById(cameraId: number | null) {
  if (cameraId === null) return null
  return cameraStore.byId.get(cameraId) || null
}

function runtimeState(cameraId: number | null) {
  return runtimeStore.recorderState(cameraId)
}

function recordingLabel(cameraId: number | null) {
  const state = runtimeState(cameraId)
  if (state === 'RECORDING') return 'REC'
  if (state === 'RECONNECTING') return '重连'
  if (state === 'STARTING') return '启动'
  return 'IDLE'
}

function recordingClass(cameraId: number | null) {
  const state = runtimeState(cameraId)
  if (state === 'RECORDING') return 'recording'
  if (state === 'RECONNECTING' || state === 'STARTING') return 'warning'
  return 'idle'
}

function streamPolicyLabel(stream: PreviewStream) {
  if (stream === 'main') return 'MAIN'
  if (stream === 'sub') return 'SUB'
  return 'AUTO'
}

function streamDetail(slot: WallSlot) {
  if (slot.activeStream === 'main') return 'MAIN'
  if (slot.activeStream === 'sub') return 'SUB'
  return streamPolicyLabel(slot.stream)
}

function revokeFrame(slot: WallSlot) {
  if (slot.frameUrl) URL.revokeObjectURL(slot.frameUrl)
  slot.frameUrl = ''
  slot.loaded = false
}

function wsUrl() {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${scheme}//${window.location.host}/ws/preview-wall`
}

function closeSlotSocket(slot: WallSlot) {
  slot.socketGeneration += 1
  if (slot.reconnectTimer !== null) {
    window.clearTimeout(slot.reconnectTimer)
    slot.reconnectTimer = null
  }
  if (!slot.socket) return
  const current = slot.socket
  slot.socket = null
  current.onopen = null
  current.onmessage = null
  current.onerror = null
  current.onclose = null
  try { current.close() } catch { /* already closed */ }
}

function resetRuntime(slot: WallSlot, state: PreviewTileState = 'idle', clearFrame = true) {
  closeSlotSocket(slot)
  if (clearFrame) revokeFrame(slot)
  slot.activeStream = null
  slot.failed = false
  slot.error = ''
  slot.state = state
  slot.resumeAfterVisibility = false
}

function scheduleSlotReconnect(index: number) {
  const slot = slots.value[index]
  if (!slot || !mounted || document.hidden || index >= layoutCount.value || !slot.startedByUser || slot.state === 'paused') return
  if (slot.reconnectTimer !== null) return
  slot.state = 'retrying'
  slot.reconnectTimer = window.setTimeout(() => {
    slot.reconnectTimer = null
    connectSlot(index)
  }, 1500)
}

function handleSlotText(index: number, raw: string) {
  const slot = slots.value[index]
  if (!slot) return
  try {
    const message = JSON.parse(raw) as {
      type?: string
      slot?: number
      stream?: ActivePreviewStream
      detail?: string
    }
    if (typeof message.slot === 'number' && message.slot !== index) return
    if (message.type === 'slot_ready' || message.type === 'slot_fallback') {
      if (message.stream === 'main' || message.stream === 'sub') slot.activeStream = message.stream
      slot.state = 'playing'
      slot.failed = false
      slot.error = ''
      return
    }
    if (message.type === 'slot_error' || message.type === 'fatal') {
      slot.failed = true
      slot.activeStream = null
      slot.state = 'error'
      slot.error = message.detail || '预览连接失败'
      closeSlotSocket(slot)
    }
  } catch {
    // JPEG preview text channel may gain additional event types later.
  }
}

function handleSlotFrame(index: number, buffer: ArrayBuffer) {
  if (buffer.byteLength < 2) return
  const bytes = new Uint8Array(buffer)
  if (bytes[0] !== index) return
  const slot = slots.value[index]
  if (!slot || index >= layoutCount.value || slot.cameraId === null) return
  const nextUrl = URL.createObjectURL(new Blob([buffer.slice(1)], { type: 'image/jpeg' }))
  const previous = slot.frameUrl
  slot.frameUrl = nextUrl
  slot.loaded = true
  slot.failed = false
  slot.error = ''
  slot.state = 'playing'
  if (previous) URL.revokeObjectURL(previous)
}

function connectSlot(index: number) {
  const slot = slots.value[index]
  if (!slot || !mounted || slot.cameraId === null || index >= layoutCount.value) return
  if (document.hidden) {
    slot.resumeAfterVisibility = true
    slot.state = 'paused'
    return
  }

  closeSlotSocket(slot)
  slot.failed = false
  slot.error = ''
  slot.activeStream = null
  slot.state = 'connecting'
  const generation = slot.socketGeneration
  const ws = markRaw(new WebSocket(wsUrl()))
  slot.socket = ws
  ws.binaryType = 'arraybuffer'

  ws.onopen = () => {
    if (slot.socketGeneration !== generation || slot.socket !== ws) return
    ws.send(JSON.stringify({
      fps: previewProfile.value.fps,
      width: previewProfile.value.width,
      slots: [{ index, camera_id: slot.cameraId, stream: slot.stream }],
    }))
  }

  ws.onmessage = (event: MessageEvent) => {
    if (slot.socketGeneration !== generation || slot.socket !== ws) return
    if (typeof event.data === 'string') handleSlotText(index, event.data)
    else if (event.data instanceof ArrayBuffer) handleSlotFrame(index, event.data)
  }

  ws.onerror = () => {
    if (slot.socketGeneration !== generation || slot.socket !== ws) return
    slot.state = 'retrying'
  }

  ws.onclose = () => {
    if (slot.socketGeneration !== generation || slot.socket !== ws) return
    slot.socket = null
    scheduleSlotReconnect(index)
  }
}

function startSlot(index: number) {
  const slot = slots.value[index]
  if (!slot || slot.cameraId === null) return
  slot.startedByUser = true
  slot.resumeAfterVisibility = false
  connectSlot(index)
}

function pauseSlot(index: number) {
  const slot = slots.value[index]
  if (!slot) return
  closeSlotSocket(slot)
  slot.state = 'paused'
  slot.failed = false
  slot.error = ''
  slot.resumeAfterVisibility = false
}

function toggleSlotPlayback(index: number) {
  const slot = slots.value[index]
  if (!slot || slot.cameraId === null) return
  if (tilePrimaryAction(slot.state) === 'pause') pauseSlot(index)
  else startSlot(index)
}

function startAllVisibleSlots() {
  activeSlots.value.forEach((slot, index) => {
    if (slot.cameraId === null) return
    if (isActiveTileState(slot.state)) return
    startSlot(index)
  })
}

function pauseAllVisibleSlots() {
  activeSlots.value.forEach((slot, index) => {
    if (slot.cameraId === null) return
    if (!isActiveTileState(slot.state)) return
    pauseSlot(index)
  })
}

function loadSavedWall() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const saved = JSON.parse(raw) as SavedWall
    if (saved.layout === 1 || saved.layout === 4 || saved.layout === 9) layoutCount.value = saved.layout
    if (Array.isArray(saved.slots)) {
      saved.slots.slice(0, 9).forEach((item, index) => {
        const stream: PreviewStream = ['auto', 'sub', 'main'].includes(item.stream) ? item.stream : 'auto'
        slots.value[index] = emptySlot(typeof item.cameraId === 'number' ? item.cameraId : null, stream)
      })
    }
  } catch {
    localStorage.removeItem(STORAGE_KEY)
  }
}

function persistWall() {
  const payload: SavedWall = {
    layout: layoutCount.value,
    slots: slots.value.map((slot) => ({ cameraId: slot.cameraId, stream: slot.stream })),
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
}

function reconcileSlots() {
  const validIds = new Set(cameras.value.map((camera) => camera.id))
  let changed = false
  slots.value.forEach((slot) => {
    if (slot.cameraId !== null && !validIds.has(slot.cameraId)) {
      resetRuntime(slot)
      Object.assign(slot, emptySlot())
      changed = true
    }
  })
  if (changed) persistWall()
}

async function loadData(force = false) {
  loading.value = true
  try {
    await cameraStore.load(force)
    reconcileSlots()
    if (!slots.value.some((slot) => slot.cameraId !== null)) autoFill()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '实时监控加载失败')
  } finally {
    loading.value = false
  }
}

function setStream(index: number, stream: PreviewStream) {
  const slot = slots.value[index]
  if (!slot || slot.stream === stream) return
  const reconnect = slot.startedByUser && slot.state !== 'paused' && slot.state !== 'idle'
  slot.stream = stream
  slot.activeStream = null
  slot.failed = false
  slot.error = ''
  persistWall()
  if (reconnect) connectSlot(index)
}

function clearSlot(index: number) {
  const slot = slots.value[index]
  if (!slot) return
  resetRuntime(slot)
  slots.value[index] = emptySlot()
  persistWall()
}

function assignCamera(index: number, cameraId: number) {
  const previousIndex = slots.value.findIndex((slot, slotIndex) => slotIndex !== index && slot.cameraId === cameraId)
  if (previousIndex >= 0) clearSlot(previousIndex)
  const destination = slots.value[index]
  if (destination) resetRuntime(destination)
  slots.value[index] = emptySlot(cameraId, 'auto')
  persistWall()
}

function assignToFirstFree(cameraId: number) {
  if (activeSlots.value.some((slot) => slot.cameraId === cameraId)) return
  const free = activeSlots.value.findIndex((slot) => slot.cameraId === null)
  if (free >= 0) assignCamera(free, cameraId)
}

function autoFill() {
  const available = enabledCameras.value.slice(0, layoutCount.value)
  for (let index = 0; index < layoutCount.value; index += 1) {
    const current = slots.value[index]
    if (current) resetRuntime(current)
    const camera = available[index]
    slots.value[index] = camera ? emptySlot(camera.id, 'auto') : emptySlot()
  }
  persistWall()
}

function clearWall() {
  slots.value.forEach((slot) => resetRuntime(slot))
  slots.value = Array.from({ length: 9 }, () => emptySlot())
  persistWall()
}

function changeLayout(value: LayoutCount) {
  if (value < layoutCount.value) {
    for (let index = value; index < slots.value.length; index += 1) {
      const slot = slots.value[index]
      if (!slot) continue
      closeSlotSocket(slot)
      revokeFrame(slot)
      slot.state = 'idle'
      slot.startedByUser = false
      slot.resumeAfterVisibility = false
      slot.activeStream = null
    }
  }
  layoutCount.value = value
  persistWall()
}

function onDragStart(cameraId: number, event: DragEvent) {
  draggingCameraId.value = cameraId
  event.dataTransfer?.setData('text/plain', String(cameraId))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function onDragEnd() {
  draggingCameraId.value = null
}

function onDrop(index: number, event: DragEvent) {
  const raw = event.dataTransfer?.getData('text/plain') || String(draggingCameraId.value || '')
  const cameraId = Number(raw)
  if (Number.isInteger(cameraId)) assignCamera(index, cameraId)
  draggingCameraId.value = null
}

async function enterFullscreen(index: number) {
  const element = document.getElementById(`wall-slot-${index}`)
  if (!element) return
  try {
    if (document.fullscreenElement === element) await document.exitFullscreen()
    else await element.requestFullscreen()
  } catch {
    ElMessage.warning('浏览器未允许全屏显示')
  }
}

function openPlayback() {
  void router.push('/recordings/playback')
}

function openCameraConfig(cameraId: number | null) {
  if (cameraId === null) return
  void router.push({ path: '/cameras', query: { camera_id: String(cameraId) } })
}

function handleTileCommand(index: number, command: string) {
  const slot = slots.value[index]
  if (!slot) return
  if (command === 'playback') openPlayback()
  else if (command === 'settings') openCameraConfig(slot.cameraId)
  else if (command === 'fullscreen') void enterFullscreen(index)
  else if (command === 'remove') clearSlot(index)
  else if (command.startsWith('stream:')) setStream(index, command.slice(7) as PreviewStream)
}

function onVisibilityChange() {
  if (document.hidden) {
    activeSlots.value.forEach((slot) => {
      const wasActive = isActiveTileState(slot.state)
      slot.resumeAfterVisibility = shouldResumeAfterVisibility(slot.startedByUser, wasActive)
      if (!wasActive) return
      closeSlotSocket(slot)
      slot.state = 'paused'
    })
    return
  }

  activeSlots.value.forEach((slot, index) => {
    if (!shouldResumeAfterVisibility(slot.startedByUser, slot.resumeAfterVisibility)) return
    slot.resumeAfterVisibility = false
    connectSlot(index)
  })
}

watch(cameras, () => reconcileSlots())

onMounted(() => {
  mounted = true
  loadSavedWall()
  void loadData()
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onBeforeUnmount(() => {
  mounted = false
  slots.value.forEach((slot) => {
    closeSlotSocket(slot)
    revokeFrame(slot)
  })
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <div class="protect-live-page" v-loading="loading">
    <header class="live-header">
      <div>
        <div class="eyebrow">LIVE</div>
        <h2>实时监控</h2>
        <p>每个画面独立开始与暂停；进入页面不会自动连接摄像头。</p>
      </div>
      <div class="header-actions">
        <div class="live-summary-pill"><span></span>{{ playingCount }} / {{ configuredCount }} 活动</div>
        <div class="profile-pill">{{ previewProfile.label }}</div>
        <el-button size="small" type="primary" :icon="VideoPlay" :disabled="configuredCount === 0 || playingCount === configuredCount" @click="startAllVisibleSlots">全部播放</el-button>
        <el-button size="small" :icon="VideoPause" :disabled="playingCount === 0" @click="pauseAllVisibleSlots">全部暂停</el-button>
        <el-button size="small" @click="autoFill">自动布局</el-button>
        <el-button size="small" plain @click="clearWall">清空</el-button>
      </div>
    </header>

    <section class="live-toolbar">
      <div class="layout-switcher" aria-label="画面布局">
        <button :class="{ active: layoutCount === 1 }" @click="changeLayout(1)">1</button>
        <button :class="{ active: layoutCount === 4 }" @click="changeLayout(4)">4</button>
        <button :class="{ active: layoutCount === 9 }" @click="changeLayout(9)">9</button>
      </div>
      <div class="camera-tray">
        <span class="tray-label">摄像头</span>
        <button
          v-for="camera in cameras"
          :key="camera.id"
          class="camera-chip"
          :class="{ assigned: assignedIds.has(camera.id), disabled: !camera.enabled }"
          :draggable="camera.enabled"
          @click="camera.enabled && assignToFirstFree(camera.id)"
          @dragstart="onDragStart(camera.id, $event)"
          @dragend="onDragEnd"
        >
          <span class="chip-dot" :class="recordingClass(camera.id)"></span>
          <span>{{ camera.name }}</span>
          <small>{{ camera.ip }}</small>
        </button>
      </div>
    </section>

    <section class="video-wall" :class="`grid-${layoutCount}`">
      <article
        v-for="(slot, index) in activeSlots"
        :id="`wall-slot-${index}`"
        :key="index"
        class="wall-slot"
        :class="[`state-${slot.state}`, { empty: slot.cameraId === null }]"
        @dragover.prevent
        @drop.prevent="onDrop(index, $event)"
      >
        <template v-if="cameraById(slot.cameraId)">
          <img v-if="slot.frameUrl" class="preview-image" :src="slot.frameUrl" :alt="cameraById(slot.cameraId)?.name" />
          <div v-else class="preview-black"></div>

          <div v-if="(slot.state === 'connecting' || slot.state === 'retrying') && !slot.frameUrl" class="tile-progress">
            <span class="loader-ring"></span>
            <small>{{ slot.state === 'retrying' ? '正在重连' : '正在连接' }}</small>
          </div>

          <div class="tile-topbar">
            <div class="camera-title">
              <span class="live-dot" :class="slot.state"></span>
              <strong>{{ cameraById(slot.cameraId)?.name }}</strong>
              <span class="rec-badge" :class="recordingClass(slot.cameraId)">{{ recordingLabel(slot.cameraId) }}</span>
            </div>
            <span class="stream-status">{{ streamDetail(slot) }}</span>
          </div>

          <div class="tile-primary-overlay">
            <button
              type="button"
              class="tile-primary-action"
              :class="{ persistent: slot.state !== 'playing' }"
              :aria-label="tilePrimaryLabel(slot.state)"
              @click.stop="toggleSlotPlayback(index)"
            >
              <VideoPause v-if="tilePrimaryAction(slot.state) === 'pause'" />
              <VideoPlay v-else />
              <span>{{ tilePrimaryLabel(slot.state) }}</span>
            </button>
          </div>

          <div v-if="slot.state === 'error'" class="tile-error-copy">
            {{ slot.error || '预览连接失败' }}
          </div>

          <div class="tile-edge-tools desktop-tools">
            <button type="button" title="录像回放" @click="openPlayback"><Clock /></button>
            <button type="button" title="摄像头设置" @click="openCameraConfig(slot.cameraId)"><Setting /></button>
            <el-dropdown trigger="click" @command="(command: PreviewStream) => setStream(index, command)">
              <button type="button" :title="`码流：${streamPolicyLabel(slot.stream)}`" class="stream-tool">{{ streamPolicyLabel(slot.stream) }}</button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="auto">AUTO · 子码流优先</el-dropdown-item>
                  <el-dropdown-item command="sub">SUB · 子码流</el-dropdown-item>
                  <el-dropdown-item command="main">MAIN · 主码流</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <button type="button" title="全屏" @click="enterFullscreen(index)"><FullScreen /></button>
            <button type="button" title="移除" @click="clearSlot(index)"><Close /></button>
          </div>

          <el-dropdown class="mobile-tools" trigger="click" @command="(command: string) => handleTileCommand(index, command)">
            <button type="button" class="mobile-more" aria-label="更多画面操作"><MoreFilled /></button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="playback">录像回放</el-dropdown-item>
                <el-dropdown-item command="settings">摄像头设置</el-dropdown-item>
                <el-dropdown-item command="stream:auto">AUTO 码流</el-dropdown-item>
                <el-dropdown-item command="stream:sub">SUB 码流</el-dropdown-item>
                <el-dropdown-item command="stream:main">MAIN 码流</el-dropdown-item>
                <el-dropdown-item command="fullscreen">全屏</el-dropdown-item>
                <el-dropdown-item divided command="remove">移除画面</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>

        <button v-else class="empty-slot" @click="enabledCameras[0] && assignCamera(index, enabledCameras[0].id)">
          <VideoCamera />
          <strong>空画面</strong>
          <span>拖入或点击上方摄像头</span>
        </button>
      </article>
    </section>

    <div class="live-note">
      <span>中央按钮只控制当前画面</span>
      <span>暂停会断开该画面的实时预览，不影响录像与其他画面</span>
      <span>切换布局不会自动启动新显示的画面</span>
    </div>
  </div>
</template>

<style scoped>
.protect-live-page{min-height:100%;padding:18px 20px 26px;background:var(--nvr-bg);box-sizing:border-box}.live-header{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:12px}.eyebrow{color:var(--nvr-subtle);font-size:8px;font-weight:800;letter-spacing:.18em}.live-header h2{margin:3px 0;font-size:20px;font-weight:650}.live-header p{margin:0;color:var(--nvr-muted);font-size:10px}.header-actions{display:flex;align-items:center;justify-content:flex-end;gap:6px;flex-wrap:wrap}.profile-pill,.live-summary-pill{height:27px;display:flex;align-items:center;gap:6px;padding:0 8px;border:1px solid var(--nvr-border);border-radius:7px;color:var(--nvr-muted);background:var(--nvr-surface);font-size:9px}.live-summary-pill>span{width:6px;height:6px;border-radius:50%;background:var(--nvr-green)}
.live-toolbar{min-height:48px;display:flex;align-items:center;gap:10px;margin-bottom:8px;padding:6px 8px;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface)}.layout-switcher{flex:none;display:flex;gap:2px;padding:2px;border-radius:6px;background:var(--nvr-input)}.layout-switcher button{width:29px;height:25px;border:0;border-radius:5px;color:var(--nvr-subtle);background:transparent;font:inherit;font-size:10px;font-weight:700;cursor:pointer}.layout-switcher button.active{color:#fff;background:var(--nvr-blue)}.camera-tray{min-width:0;display:flex;align-items:center;gap:5px;overflow-x:auto;scrollbar-width:thin}.tray-label{flex:none;padding:0 3px;color:var(--nvr-subtle);font-size:8px;font-weight:700}.camera-chip{flex:none;min-width:102px;height:32px;display:grid;grid-template-columns:7px auto;grid-template-rows:15px 11px;column-gap:6px;padding:3px 7px;border:1px solid transparent;border-radius:6px;color:var(--nvr-muted);background:var(--nvr-input);font:inherit;text-align:left;cursor:grab}.camera-chip:hover{border-color:color-mix(in srgb,var(--nvr-blue) 35%,var(--nvr-border));background:var(--nvr-hover)}.camera-chip.assigned{border-color:color-mix(in srgb,var(--nvr-blue) 18%,var(--nvr-border))}.camera-chip.disabled{opacity:.38;cursor:not-allowed}.chip-dot{grid-row:1/3;align-self:center;width:6px;height:6px;border-radius:50%;background:#667386}.chip-dot.recording{background:var(--nvr-green)}.chip-dot.warning{background:var(--nvr-yellow)}.camera-chip>span:not(.chip-dot){align-self:end;overflow:hidden;font-size:9px;font-weight:650;text-overflow:ellipsis;white-space:nowrap}.camera-chip small{overflow:hidden;color:var(--nvr-subtle);font-size:7px;text-overflow:ellipsis;white-space:nowrap}
.video-wall{display:grid;gap:3px;width:100%;background:#04070a}.video-wall.grid-1{grid-template-columns:1fr}.video-wall.grid-4{grid-template-columns:repeat(2,minmax(0,1fr))}.video-wall.grid-9{grid-template-columns:repeat(3,minmax(0,1fr))}.wall-slot{position:relative;aspect-ratio:16/9;min-width:0;overflow:hidden;background:#020406;box-shadow:inset 0 0 0 1px rgba(255,255,255,.045)}.preview-image,.preview-black{display:block;width:100%;height:100%;object-fit:contain;background:#000}.preview-black{position:absolute;inset:0}.wall-slot::after{content:'';position:absolute;inset:0;z-index:1;pointer-events:none;box-shadow:inset 0 0 35px rgba(0,0,0,.24)}.wall-slot.state-error{box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--nvr-red) 38%,transparent)}
.tile-topbar{position:absolute;z-index:4;inset:0 0 auto;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:7px 8px 16px;background:linear-gradient(180deg,rgba(0,0,0,.66),transparent);pointer-events:none}.camera-title{min-width:0;display:flex;align-items:center;gap:6px}.camera-title strong{max-width:170px;overflow:hidden;color:#f1f5f8;font-size:9.5px;text-overflow:ellipsis;white-space:nowrap}.live-dot{width:6px;height:6px;flex:none;border-radius:50%;background:#586677}.live-dot.playing{background:#2bd38a;box-shadow:0 0 0 3px rgba(43,211,138,.1)}.live-dot.connecting,.live-dot.retrying{background:#e4ae42}.live-dot.error{background:#e25d61}.rec-badge,.stream-status{padding:2px 5px;border-radius:4px;font-size:7px;font-weight:800;letter-spacing:.035em}.rec-badge{color:#7c8998;background:rgba(9,13,18,.7)}.rec-badge.recording{color:#8ae4b7;background:rgba(43,184,116,.14)}.rec-badge.warning{color:#f1c770;background:rgba(207,154,47,.14)}.stream-status{flex:none;color:#a9b6c5;background:rgba(7,11,16,.7)}
.tile-primary-overlay{position:absolute;z-index:5;inset:0;display:grid;place-items:center;pointer-events:none}.tile-primary-action{min-width:58px;height:52px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;padding:0 10px;border:0;border-radius:11px;color:#fff;background:rgba(7,12,18,.7);backdrop-filter:blur(9px);font:inherit;cursor:pointer;pointer-events:auto;opacity:0;transform:scale(.97);transition:opacity .14s ease,transform .14s ease,background .14s ease}.tile-primary-action.persistent,.wall-slot:hover .tile-primary-action,.tile-primary-action:focus-visible{opacity:1;transform:scale(1)}.tile-primary-action:hover{background:rgba(28,83,172,.84)}.tile-primary-action :deep(svg){width:20px;height:20px}.tile-primary-action span{font-size:8px;font-weight:700}.tile-primary-action:focus-visible{outline:2px solid rgba(85,150,255,.9);outline-offset:2px}.tile-progress{position:absolute;z-index:3;left:50%;top:58%;display:flex;align-items:center;gap:6px;color:#7c8a9b;transform:translate(-50%,-50%)}.tile-progress small{font-size:8px}.loader-ring{width:14px;height:14px;border:1.5px solid #26313d;border-top-color:var(--nvr-blue);border-radius:50%;animation:spin .8s linear infinite}.tile-error-copy{position:absolute;z-index:4;left:50%;top:66%;max-width:70%;padding:4px 7px;border-radius:5px;color:#e59799;background:rgba(34,8,10,.58);font-size:7.5px;text-align:center;transform:translateX(-50%)}
.tile-edge-tools{position:absolute;z-index:6;right:7px;bottom:7px;display:flex;align-items:center;gap:2px;opacity:0;transform:translateY(3px);transition:opacity .14s ease,transform .14s ease}.wall-slot:hover .tile-edge-tools,.tile-edge-tools:focus-within{opacity:1;transform:none}.tile-edge-tools button,.mobile-more{height:29px;min-width:29px;display:grid;place-items:center;padding:0 7px;border:0;border-radius:6px;color:rgba(235,241,247,.76);background:rgba(6,10,15,.72);backdrop-filter:blur(7px);font:inherit;font-size:7px;font-weight:750;cursor:pointer}.tile-edge-tools button:hover,.mobile-more:hover{color:#fff;background:rgba(255,255,255,.12)}.tile-edge-tools :deep(svg),.mobile-more :deep(svg){width:14px}.stream-tool{min-width:42px!important}.mobile-tools{display:none;position:absolute;z-index:7;right:7px;bottom:7px}.mobile-more{width:31px}.empty-slot{width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;border:1px dashed transparent;color:#455263;background:transparent;font:inherit;cursor:pointer}.empty-slot:hover{border-color:color-mix(in srgb,var(--nvr-blue) 20%,transparent);color:#78899e;background:color-mix(in srgb,var(--nvr-blue) 2%,transparent)}.empty-slot :deep(svg){width:23px}.empty-slot strong{font-size:9px}.empty-slot span{font-size:7.5px}.live-note{display:flex;align-items:center;gap:13px;flex-wrap:wrap;margin-top:9px;color:var(--nvr-subtle);font-size:8px}.wall-slot:fullscreen{width:100vw;height:100vh;aspect-ratio:auto}.wall-slot:fullscreen .preview-image{object-fit:contain}.wall-slot:fullscreen .tile-edge-tools,.wall-slot:fullscreen .tile-primary-action{opacity:1;transform:none}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:960px){.protect-live-page{padding:14px}.live-header{align-items:flex-start;flex-direction:column}.header-actions{justify-content:flex-start}.video-wall.grid-9{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:620px){.protect-live-page{padding:9px}.live-toolbar{align-items:flex-start;flex-direction:column}.camera-tray{width:100%}.video-wall.grid-4,.video-wall.grid-9{grid-template-columns:1fr}.wall-slot{aspect-ratio:16/10}.desktop-tools{display:none}.mobile-tools{display:block}.tile-primary-action{opacity:1}.camera-title strong{max-width:125px}.live-note{display:none}}
</style>