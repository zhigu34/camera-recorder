<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import {
  Close,
  FullScreen,
  RefreshRight,
  Setting,
  VideoCamera,
  VideoPlay,
} from '@element-plus/icons-vue'

type LayoutCount = 1 | 4 | 9
type PreviewStream = 'auto' | 'sub' | 'main'
type ActivePreviewStream = 'sub' | 'main'
type ConnectionState = 'idle' | 'connecting' | 'connected' | 'retrying'

interface Camera {
  id: number
  name: string
  ip: string
  rtsp_path: string
  sub_rtsp_path?: string | null
  enabled: boolean
}

interface RecorderRuntime {
  camera_id: number
  state: string
}

interface SystemStatus {
  recorders?: RecorderRuntime[]
}

interface WallSlot {
  cameraId: number | null
  stream: PreviewStream
  activeStream: ActivePreviewStream | null
  frameUrl: string
  loaded: boolean
  failed: boolean
  error: string
}

interface SavedWall {
  layout?: LayoutCount
  slots?: Array<{ cameraId: number | null; stream: PreviewStream }>
}

const STORAGE_KEY = 'nvr-video-wall-v1'
const cameras = ref<Camera[]>([])
const systemStatus = ref<SystemStatus | null>(null)
const loading = ref(false)
const layoutCount = ref<LayoutCount>(4)
const wallPaused = ref(false)
const draggingCameraId = ref<number | null>(null)
const connectionState = ref<ConnectionState>('idle')
let statusTimer: number | null = null
let reconnectTimer: number | null = null
let connectTimer: number | null = null
let socket: WebSocket | null = null
let socketGeneration = 0
let mounted = false

function emptySlot(): WallSlot {
  return { cameraId: null, stream: 'auto', activeStream: null, frameUrl: '', loaded: false, failed: false, error: '' }
}

const slots = ref<WallSlot[]>(Array.from({ length: 9 }, emptySlot))
const activeSlots = computed(() => slots.value.slice(0, layoutCount.value))
const enabledCameras = computed(() => cameras.value.filter((camera) => camera.enabled))
const assignedIds = computed(() => new Set(activeSlots.value.map((slot) => slot.cameraId).filter((id): id is number => id !== null)))
const configuredSlots = computed(() => activeSlots.value
  .map((slot, index) => ({ slot, index }))
  .filter((item) => item.slot.cameraId !== null))

const previewProfile = computed(() => {
  if (layoutCount.value === 1) return { fps: 8, width: 1280, label: '8fps · 1280px' }
  if (layoutCount.value === 4) return { fps: 5, width: 640, label: '5fps · 640px' }
  return { fps: 3, width: 480, label: '3fps · 480px' }
})

function cameraById(cameraId: number | null) {
  if (cameraId === null) return null
  return cameras.value.find((camera) => camera.id === cameraId) || null
}

function runtimeState(cameraId: number | null) {
  if (cameraId === null) return 'STOPPED'
  return systemStatus.value?.recorders?.find((item) => item.camera_id === cameraId)?.state || 'STOPPED'
}

function stateLabel(cameraId: number | null) {
  const state = runtimeState(cameraId)
  if (state === 'RECORDING') return 'REC'
  if (state === 'RECONNECTING') return '重连中'
  if (state === 'STARTING') return '启动中'
  return '未录像'
}

function stateClass(cameraId: number | null) {
  const state = runtimeState(cameraId)
  if (state === 'RECORDING') return 'recording'
  if (state === 'RECONNECTING' || state === 'STARTING') return 'warning'
  return 'idle'
}

function streamPolicyLabel(stream: PreviewStream) {
  if (stream === 'main') return '主码流'
  if (stream === 'sub') return '子码流'
  return 'AUTO / 子码流优先'
}

function activeStreamLabel(stream: ActivePreviewStream | null) {
  if (stream === 'main') return '主码流'
  if (stream === 'sub') return '子码流'
  return '确认中'
}

function revokeFrame(slot: WallSlot) {
  if (slot.frameUrl) URL.revokeObjectURL(slot.frameUrl)
  slot.frameUrl = ''
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
        slots.value[index] = {
          cameraId: typeof item.cameraId === 'number' ? item.cameraId : null,
          stream,
          activeStream: null,
          frameUrl: '',
          loaded: false,
          failed: false,
          error: '',
        }
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

function wsUrl() {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${scheme}//${window.location.host}/ws/preview-wall`
}

function closeSocket() {
  socketGeneration += 1
  if (socket) {
    const current = socket
    socket = null
    current.onopen = null
    current.onmessage = null
    current.onerror = null
    current.onclose = null
    try { current.close() } catch { /* already closed */ }
  }
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

function markSlotsConnecting() {
  configuredSlots.value.forEach(({ slot }) => {
    slot.failed = false
    slot.error = ''
    slot.activeStream = null
    slot.loaded = Boolean(slot.frameUrl)
  })
}

function scheduleReconnect() {
  if (!mounted || wallPaused.value || document.hidden || configuredSlots.value.length === 0) return
  if (reconnectTimer !== null) return
  connectionState.value = 'retrying'
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null
    connectWall()
  }, 1500)
}

function handleTextMessage(raw: string) {
  try {
    const message = JSON.parse(raw) as {
      type?: string
      slot?: number
      stream?: ActivePreviewStream
      detail?: string
    }
    if ((message.type === 'slot_ready' || message.type === 'slot_fallback') && typeof message.slot === 'number') {
      const slot = slots.value[message.slot]
      if (slot && (message.stream === 'main' || message.stream === 'sub')) {
        slot.activeStream = message.stream
        slot.failed = false
        slot.error = ''
      }
    } else if (message.type === 'slot_error' && typeof message.slot === 'number') {
      const slot = slots.value[message.slot]
      if (slot) {
        slot.failed = true
        slot.loaded = false
        slot.activeStream = null
        slot.error = message.detail || '预览连接失败'
      }
    } else if (message.type === 'fatal') {
      ElMessage.error(message.detail || '多画面预览连接失败')
    }
  } catch {
    // Ignore unknown text frames; JPEG frames are binary.
  }
}

function handleBinaryMessage(buffer: ArrayBuffer) {
  if (buffer.byteLength < 4) return
  const bytes = new Uint8Array(buffer)
  const index = bytes[0]
  const slot = slots.value[index]
  if (!slot || index >= layoutCount.value || slot.cameraId === null) return
  const jpeg = buffer.slice(1)
  const nextUrl = URL.createObjectURL(new Blob([jpeg], { type: 'image/jpeg' }))
  const previous = slot.frameUrl
  slot.frameUrl = nextUrl
  slot.loaded = true
  slot.failed = false
  slot.error = ''
  if (previous) URL.revokeObjectURL(previous)
}

function connectWall() {
  closeSocket()
  if (!mounted || wallPaused.value || document.hidden || configuredSlots.value.length === 0) {
    connectionState.value = 'idle'
    return
  }

  const generation = socketGeneration
  const ws = new WebSocket(wsUrl())
  socket = ws
  ws.binaryType = 'arraybuffer'
  connectionState.value = 'connecting'
  markSlotsConnecting()

  ws.onopen = () => {
    if (generation !== socketGeneration || socket !== ws) return
    connectionState.value = 'connected'
    ws.send(JSON.stringify({
      fps: previewProfile.value.fps,
      width: previewProfile.value.width,
      slots: configuredSlots.value.map(({ slot, index }) => ({
        index,
        camera_id: slot.cameraId,
        stream: slot.stream,
      })),
    }))
  }

  ws.onmessage = (event: MessageEvent) => {
    if (generation !== socketGeneration || socket !== ws) return
    if (typeof event.data === 'string') handleTextMessage(event.data)
    else if (event.data instanceof ArrayBuffer) handleBinaryMessage(event.data)
  }

  ws.onerror = () => {
    if (generation !== socketGeneration || socket !== ws) return
    connectionState.value = 'retrying'
  }

  ws.onclose = () => {
    if (generation !== socketGeneration || socket !== ws) return
    socket = null
    scheduleReconnect()
  }
}

function scheduleConnect() {
  if (connectTimer !== null) window.clearTimeout(connectTimer)
  connectTimer = window.setTimeout(() => {
    connectTimer = null
    connectWall()
  }, 80)
}

async function loadData() {
  loading.value = true
  try {
    const [cameraRes, statusRes] = await Promise.all([
      axios.get<Camera[]>('/api/cameras'),
      axios.get<SystemStatus>('/api/system/status'),
    ])
    cameras.value = cameraRes.data
    systemStatus.value = statusRes.data
    const validIds = new Set(cameraRes.data.map((camera) => camera.id))
    slots.value.forEach((slot) => {
      if (slot.cameraId !== null && !validIds.has(slot.cameraId)) {
        revokeFrame(slot)
        Object.assign(slot, emptySlot())
      }
    })
    if (!slots.value.some((slot) => slot.cameraId !== null)) autoFill(false)
    scheduleConnect()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '实时监控加载失败')
  } finally {
    loading.value = false
  }
}

async function refreshStatus() {
  try {
    systemStatus.value = (await axios.get<SystemStatus>('/api/system/status')).data
  } catch {
    // Keep last known recorder state.
  }
}

function restartSlot(index: number) {
  const slot = slots.value[index]
  slot.failed = false
  slot.loaded = false
  slot.activeStream = null
  slot.error = ''
  revokeFrame(slot)
  scheduleConnect()
}

function setStream(index: number, stream: PreviewStream) {
  const slot = slots.value[index]
  if (slot.stream === stream) return
  slot.stream = stream
  slot.failed = false
  slot.loaded = false
  slot.activeStream = null
  slot.error = ''
  revokeFrame(slot)
  persistWall()
  scheduleConnect()
}

function clearSlot(index: number) {
  revokeFrame(slots.value[index])
  slots.value[index] = emptySlot()
  persistWall()
  scheduleConnect()
}

function assignCamera(index: number, cameraId: number) {
  const previousIndex = slots.value.findIndex((slot, slotIndex) => slotIndex !== index && slot.cameraId === cameraId)
  if (previousIndex >= 0) {
    revokeFrame(slots.value[previousIndex])
    slots.value[previousIndex] = emptySlot()
  }
  revokeFrame(slots.value[index])
  slots.value[index] = { cameraId, stream: 'auto', activeStream: null, frameUrl: '', loaded: false, failed: false, error: '' }
  persistWall()
  scheduleConnect()
}

function assignToFirstFree(cameraId: number) {
  const existing = activeSlots.value.findIndex((slot) => slot.cameraId === cameraId)
  if (existing >= 0) return
  const free = activeSlots.value.findIndex((slot) => slot.cameraId === null)
  if (free >= 0) assignCamera(free, cameraId)
}

function autoFill(reconnect = true) {
  const available = enabledCameras.value.slice(0, layoutCount.value)
  for (let index = 0; index < layoutCount.value; index += 1) {
    revokeFrame(slots.value[index])
    const camera = available[index]
    slots.value[index] = camera
      ? { cameraId: camera.id, stream: 'auto', activeStream: null, frameUrl: '', loaded: false, failed: false, error: '' }
      : emptySlot()
  }
  persistWall()
  if (reconnect) scheduleConnect()
}

function clearWall() {
  slots.value.forEach(revokeFrame)
  slots.value = Array.from({ length: 9 }, emptySlot)
  persistWall()
  connectWall()
}

function changeLayout(value: LayoutCount) {
  layoutCount.value = value
  for (let index = value; index < slots.value.length; index += 1) revokeFrame(slots.value[index])
  persistWall()
  scheduleConnect()
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
    await element.requestFullscreen()
  } catch {
    ElMessage.warning('浏览器未允许全屏显示')
  }
}

function openPlayback() {
  window.history.pushState({}, '', '/recordings/browser')
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function openCameraConfig() {
  window.history.pushState({}, '', '/cameras')
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function togglePause() {
  wallPaused.value = !wallPaused.value
  if (wallPaused.value) {
    closeSocket()
    connectionState.value = 'idle'
  } else {
    scheduleConnect()
  }
}

function onVisibilityChange() {
  if (document.hidden) {
    closeSocket()
    connectionState.value = 'idle'
  } else if (!wallPaused.value) {
    scheduleConnect()
  }
}

onMounted(() => {
  mounted = true
  loadSavedWall()
  void loadData()
  statusTimer = window.setInterval(refreshStatus, 5000)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onBeforeUnmount(() => {
  mounted = false
  closeSocket()
  if (statusTimer !== null) window.clearInterval(statusTimer)
  if (connectTimer !== null) window.clearTimeout(connectTimer)
  slots.value.forEach(revokeFrame)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <div class="wall-page" v-loading="loading">
    <header class="wall-header">
      <div>
        <div class="eyebrow">LIVE MONITORING</div>
        <h2>实时监控</h2>
        <p>多画面通过单条 WebSocket 复用 JPEG 帧，避免 MJPEG 长连接数量限制；录像主链路不受影响。</p>
      </div>
      <div class="header-actions">
        <div class="connection-pill" :class="connectionState">
          <span class="connection-dot"></span>
          {{ connectionState === 'connected' ? '画面已连接' : connectionState === 'connecting' ? '正在连接' : connectionState === 'retrying' ? '自动重连' : '未连接' }}
        </div>
        <div class="profile-pill">{{ previewProfile.label }}</div>
        <el-button size="small" @click="togglePause">{{ wallPaused ? '恢复画面' : '暂停画面' }}</el-button>
        <el-button size="small" @click="autoFill()">自动布局</el-button>
        <el-button size="small" plain @click="clearWall">清空</el-button>
      </div>
    </header>

    <section class="wall-toolbar">
      <div class="layout-switcher" aria-label="画面布局">
        <button :class="{ active: layoutCount === 1 }" @click="changeLayout(1)">1</button>
        <button :class="{ active: layoutCount === 4 }" @click="changeLayout(4)">4</button>
        <button :class="{ active: layoutCount === 9 }" @click="changeLayout(9)">9</button>
      </div>
      <div class="camera-tray">
        <div class="tray-label">摄像头</div>
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
          <span class="chip-dot" :class="stateClass(camera.id)"></span>
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
        :class="{ empty: slot.cameraId === null, failed: slot.failed }"
        @dragover.prevent
        @drop.prevent="onDrop(index, $event)"
      >
        <template v-if="cameraById(slot.cameraId)">
          <img v-if="slot.frameUrl" class="preview-image" :src="slot.frameUrl" :alt="cameraById(slot.cameraId)?.name" />

          <div v-if="!slot.loaded && !slot.failed && !wallPaused" class="slot-loading-ws">
            <span class="loader-ring"></span>
            <span>等待 {{ cameraById(slot.cameraId)?.name }} 第一帧…</span>
          </div>

          <div v-if="wallPaused" class="slot-state-message">
            <VideoCamera />
            <strong>画面已暂停</strong>
            <span>录像仍然继续</span>
          </div>

          <div v-else-if="slot.failed" class="slot-state-message error">
            <VideoCamera />
            <strong>预览连接失败</strong>
            <span>{{ slot.error || '请检查码流路径或网络' }}</span>
            <el-button size="small" @click="restartSlot(index)">重新连接</el-button>
          </div>

          <div class="slot-topbar">
            <div class="camera-title">
              <span class="live-dot" :class="slot.failed ? 'error' : slot.loaded ? 'live' : 'waiting'"></span>
              <strong>{{ cameraById(slot.cameraId)?.name }}</strong>
              <span>{{ cameraById(slot.cameraId)?.ip }}</span>
            </div>
            <div class="slot-badges">
              <span class="rec-badge" :class="stateClass(slot.cameraId)">{{ stateLabel(slot.cameraId) }}</span>
              <span class="active-stream-badge" :class="slot.activeStream || 'pending'">
                {{ activeStreamLabel(slot.activeStream) }}
              </span>
              <el-dropdown trigger="click" @command="(command: PreviewStream) => setStream(index, command)">
                <button class="stream-button" :title="`码流策略：${streamPolicyLabel(slot.stream)}`">
                  {{ slot.stream === 'main' ? 'MAIN' : slot.stream === 'sub' ? 'SUB' : 'AUTO' }}
                </button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="auto">AUTO · 子码流优先</el-dropdown-item>
                    <el-dropdown-item command="sub">SUB · 子码流</el-dropdown-item>
                    <el-dropdown-item command="main">MAIN · 主码流</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>

          <div class="slot-actions">
            <button title="重新连接" @click="restartSlot(index)"><RefreshRight /></button>
            <button title="摄像头配置" @click="openCameraConfig"><Setting /></button>
            <button title="录像回放" @click="openPlayback"><VideoPlay /></button>
            <button title="全屏" @click="enterFullscreen(index)"><FullScreen /></button>
            <button title="移除" @click="clearSlot(index)"><Close /></button>
          </div>

          <div class="slot-footer">
            <span>实际：{{ activeStreamLabel(slot.activeStream) }} · 策略：{{ streamPolicyLabel(slot.stream) }}</span>
            <span>{{ previewProfile.label }}</span>
          </div>
        </template>

        <button v-else class="empty-slot" @click="enabledCameras[0] && assignCamera(index, enabledCameras[0].id)">
          <VideoCamera />
          <strong>空画面</strong>
          <span>拖入或点击上方摄像头</span>
        </button>
      </article>
    </section>

    <div class="wall-note">
      <span><i class="note-dot green"></i>录像中</span>
      <span><i class="note-dot yellow"></i>重连 / 启动</span>
      <span><i class="note-dot gray"></i>未录像</span>
      <span>画面右上角“主码流/子码流”表示实际生效码流；AUTO 只是选择策略。</span>
      <span>码流路径等设备配置统一在“摄像头”页面管理。</span>
    </div>
  </div>
</template>

<style scoped>
.wall-page { min-height: 100%; padding: 20px 22px 26px; background: #080c11; }
.wall-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 15px; }
.eyebrow { color: #506079; font-size: 9px; font-weight: 800; letter-spacing: .18em; }
h2 { margin: 3px 0 3px; font-size: 21px; font-weight: 650; }
p { margin: 0; color: #6f7c8d; font-size: 11px; }
.header-actions { display: flex; align-items: center; justify-content: flex-end; gap: 7px; flex-wrap: wrap; }
.profile-pill, .connection-pill { height: 28px; display: flex; align-items: center; gap: 6px; padding: 0 9px; color: #7f8da0; border: 1px solid var(--nvr-border); border-radius: 6px; background: #0e141b; font-size: 10px; }
.connection-dot { width: 6px; height: 6px; border-radius: 50%; background: #526073; }
.connection-pill.connected { color: #93ddb9; }.connection-pill.connected .connection-dot { background: var(--nvr-green); box-shadow: 0 0 0 3px rgba(46,204,138,.1); }
.connection-pill.connecting, .connection-pill.retrying { color: #e6bb68; }.connection-pill.connecting .connection-dot, .connection-pill.retrying .connection-dot { background: var(--nvr-yellow); }
.wall-toolbar { display: flex; align-items: center; gap: 12px; min-height: 52px; margin-bottom: 10px; padding: 8px 10px; border: 1px solid var(--nvr-border); border-radius: 8px; background: #0d1218; }
.layout-switcher { flex: 0 0 auto; display: flex; gap: 2px; padding: 3px; border: 1px solid var(--nvr-border); border-radius: 6px; background: #080c11; }
.layout-switcher button { width: 30px; height: 26px; border: 0; border-radius: 4px; color: #718095; background: transparent; cursor: pointer; font-size: 11px; font-weight: 700; }
.layout-switcher button.active { color: white; background: #2768d8; }
.camera-tray { min-width: 0; display: flex; align-items: center; gap: 6px; overflow-x: auto; scrollbar-width: thin; }
.tray-label { flex: 0 0 auto; margin: 0 3px 0 2px; color: #536276; font-size: 9px; font-weight: 700; text-transform: uppercase; }
.camera-chip { flex: 0 0 auto; min-width: 104px; height: 34px; display: grid; grid-template-columns: 7px auto; grid-template-rows: 16px 12px; column-gap: 6px; padding: 3px 8px; color: #9ba8b7; border: 1px solid var(--nvr-border); border-radius: 6px; background: #10161e; cursor: grab; text-align: left; }
.camera-chip:hover { border-color: rgba(76,141,255,.42); background: #141c26; }.camera-chip.assigned { border-color: rgba(76,141,255,.22); }.camera-chip.disabled { opacity: .4; cursor: not-allowed; }
.chip-dot { grid-row: 1 / 3; align-self: center; width: 6px; height: 6px; border-radius: 50%; background: #526073; }.chip-dot.recording { background: var(--nvr-green); }.chip-dot.warning { background: var(--nvr-yellow); }.camera-chip > span:not(.chip-dot) { align-self: end; font-size: 10px; font-weight: 650; }.camera-chip small { color: #526073; font-size: 8px; }
.video-wall { display: grid; gap: 3px; width: 100%; background: #05080c; }.video-wall.grid-1 { grid-template-columns: 1fr; }.video-wall.grid-4 { grid-template-columns: repeat(2, minmax(0, 1fr)); }.video-wall.grid-9 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.wall-slot { position: relative; aspect-ratio: 16/9; min-width: 0; overflow: hidden; background: #070a0e; box-shadow: inset 0 0 0 1px rgba(255,255,255,.045); }.wall-slot:after { content:''; position:absolute; inset:0; pointer-events:none; box-shadow: inset 0 0 42px rgba(0,0,0,.22); }.wall-slot.failed { box-shadow: inset 0 0 0 1px rgba(240,93,94,.35); }
.preview-image { width: 100%; height: 100%; object-fit: contain; display: block; background: black; }
.slot-topbar { position: absolute; z-index: 4; inset: 0 0 auto 0; display: flex; justify-content: space-between; gap: 8px; align-items: center; padding: 7px 8px 16px; background: linear-gradient(to bottom, rgba(0,0,0,.68), transparent); pointer-events: none; }.camera-title { min-width: 0; display: flex; align-items: center; gap: 6px; }.camera-title strong { max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #eef3f8; font-size: 10px; }.camera-title > span:last-child { color: rgba(255,255,255,.42); font-size: 8px; }.live-dot { width: 6px; height: 6px; border-radius: 50%; }.live-dot.live { background: #29d98c; box-shadow: 0 0 0 3px rgba(41,217,140,.12); }.live-dot.waiting { background: var(--nvr-yellow); }.live-dot.error { background: var(--nvr-red); }
.slot-badges { display:flex; align-items:center; gap:5px; pointer-events:auto; }.rec-badge, .active-stream-badge, .stream-button { padding: 3px 5px; border-radius: 4px; font-size: 7px; font-weight:800; letter-spacing:.04em; }.rec-badge { color:#8491a1; background:rgba(15,20,27,.7); }.rec-badge.recording { color:#87e5b7; background:rgba(46,204,138,.12); }.rec-badge.warning { color:#ffd37b; background:rgba(245,185,66,.12); }.active-stream-badge { border:1px solid transparent; }.active-stream-badge.sub { color:#86d7ff; border-color:rgba(80,178,255,.22); background:rgba(47,139,218,.14); }.active-stream-badge.main { color:#e8c879; border-color:rgba(230,185,66,.24); background:rgba(196,145,38,.15); }.active-stream-badge.pending { color:#748398; border-color:rgba(255,255,255,.07); background:rgba(15,20,27,.64); }.stream-button { border:1px solid rgba(255,255,255,.1); color:#aab5c2; background:rgba(10,14,19,.78); cursor:pointer; }
.slot-actions { position:absolute; z-index:5; top:50%; left:50%; display:flex; gap:4px; opacity:0; transform:translate(-50%,-50%); transition:opacity .15s ease; }.wall-slot:hover .slot-actions { opacity:1; }.slot-actions button { width:30px; height:30px; display:grid; place-items:center; border:1px solid rgba(255,255,255,.11); border-radius:6px; color:#d5dde6; background:rgba(7,10,14,.78); backdrop-filter:blur(5px); cursor:pointer; }.slot-actions button:hover { color:white; background:rgba(38,104,216,.88); }.slot-actions :deep(svg) { width:14px; }
.slot-footer { position:absolute; z-index:4; inset:auto 0 0; display:flex; justify-content:space-between; padding:14px 8px 6px; color:rgba(255,255,255,.42); background:linear-gradient(to top,rgba(0,0,0,.58),transparent); font-size:8px; opacity:0; transition:.15s ease; }.wall-slot:hover .slot-footer { opacity:1; }
.slot-loading-ws, .slot-state-message { position:absolute; z-index:2; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:8px; color:#66768a; background:#070a0e; font-size:10px; text-align:center; }.loader-ring { width:20px; height:20px; border:2px solid #202a36; border-top-color:var(--nvr-blue); border-radius:50%; animation:spin .8s linear infinite; }.slot-state-message :deep(svg) { width:26px; color:#435267; }.slot-state-message strong { color:#8b98a8; font-size:11px; }.slot-state-message span { max-width:75%; color:#526073; font-size:9px; }.slot-state-message.error strong { color:#f48c8d; }.slot-state-message.error :deep(svg) { color:#b54648; }
.empty-slot { width:100%; height:100%; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:7px; border:1px dashed transparent; color:#3f4b5b; background:transparent; cursor:pointer; }.empty-slot:hover { color:#75859a; border-color:rgba(76,141,255,.2); background:rgba(76,141,255,.025); }.empty-slot :deep(svg) { width:24px; }.empty-slot strong { font-size:10px; }.empty-slot span { font-size:8px; }
.wall-note { display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-top:10px; color:#556477; font-size:9px; }.wall-note span { display:flex; align-items:center; gap:5px; }.note-dot { width:6px; height:6px; border-radius:50%; }.note-dot.green { background:var(--nvr-green); }.note-dot.yellow { background:var(--nvr-yellow); }.note-dot.gray { background:#526073; }
.wall-slot:fullscreen { width:100vw; height:100vh; aspect-ratio:auto; border-radius:0; background:black; }.wall-slot:fullscreen .preview-image { object-fit:contain; }.wall-slot:fullscreen .slot-actions,.wall-slot:fullscreen .slot-footer { opacity:1; }
@keyframes spin { to { transform:rotate(360deg); } }
@media(max-width:960px) { .wall-page{padding:16px}.wall-header{flex-direction:column;align-items:flex-start}.header-actions{justify-content:flex-start}.video-wall.grid-9{grid-template-columns:repeat(2,minmax(0,1fr))} }
@media(max-width:620px) { .wall-page{padding:10px}.wall-toolbar{align-items:flex-start;flex-direction:column}.camera-tray{width:100%}.video-wall.grid-4,.video-wall.grid-9{grid-template-columns:1fr}.wall-slot{aspect-ratio:16/10} }
</style>
