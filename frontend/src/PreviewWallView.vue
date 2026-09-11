<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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

interface Camera {
  id: number
  name: string
  ip: string
  rtsp_path: string
  sub_rtsp_path?: string | null
  enabled: boolean
  status?: string
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
  nonce: number
  failed: boolean
  loaded: boolean
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
const configVisible = ref(false)
const configCameraId = ref<number | null>(null)
const subPathDraft = ref('')
const savingSubPath = ref(false)
let statusTimer: number | null = null

function emptySlot(): WallSlot {
  return { cameraId: null, stream: 'auto', nonce: 0, failed: false, loaded: false }
}

const slots = ref<WallSlot[]>(Array.from({ length: 9 }, emptySlot))

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
          nonce: 0,
          failed: false,
          loaded: false,
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

const activeSlots = computed(() => slots.value.slice(0, layoutCount.value))
const enabledCameras = computed(() => cameras.value.filter((camera) => camera.enabled))
const assignedIds = computed(() => new Set(activeSlots.value.map((slot) => slot.cameraId).filter((id): id is number => id !== null)))

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

function streamLabel(stream: PreviewStream) {
  if (stream === 'main') return '主码流'
  if (stream === 'sub') return '子码流'
  return '自动/子码流优先'
}

function previewUrl(slot: WallSlot) {
  const camera = cameraById(slot.cameraId)
  if (!camera || !camera.enabled || wallPaused.value) return ''
  const query = new URLSearchParams({
    stream: slot.stream,
    fps: String(previewProfile.value.fps),
    width: String(previewProfile.value.width),
    v: String(slot.nonce),
  })
  return `/api/cameras/${camera.id}/preview.mjpeg?${query.toString()}`
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
      if (slot.cameraId !== null && !validIds.has(slot.cameraId)) slot.cameraId = null
    })
    if (!slots.value.some((slot) => slot.cameraId !== null)) autoFill()
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
    // Keep the last known state; preview streams can continue independently.
  }
}

function restartSlot(index: number) {
  const slot = slots.value[index]
  slot.failed = false
  slot.loaded = false
  slot.nonce += 1
}

function setStream(index: number, stream: PreviewStream) {
  const slot = slots.value[index]
  if (slot.stream === stream) return
  slot.stream = stream
  restartSlot(index)
  persistWall()
}

function clearSlot(index: number) {
  slots.value[index] = emptySlot()
  persistWall()
}

function assignCamera(index: number, cameraId: number) {
  const previousIndex = slots.value.findIndex((slot, slotIndex) => slotIndex !== index && slot.cameraId === cameraId)
  if (previousIndex >= 0) slots.value[previousIndex] = emptySlot()
  slots.value[index] = { cameraId, stream: 'auto', nonce: Date.now(), failed: false, loaded: false }
  persistWall()
}

function autoFill() {
  const available = enabledCameras.value.slice(0, layoutCount.value)
  for (let index = 0; index < layoutCount.value; index += 1) {
    const camera = available[index]
    slots.value[index] = camera
      ? { cameraId: camera.id, stream: 'auto', nonce: Date.now() + index, failed: false, loaded: false }
      : emptySlot()
  }
  persistWall()
}

function clearWall() {
  for (let index = 0; index < slots.value.length; index += 1) slots.value[index] = emptySlot()
  persistWall()
}

function changeLayout(value: LayoutCount) {
  layoutCount.value = value
  slots.value.slice(0, value).forEach((slot) => {
    slot.failed = false
    slot.loaded = false
    slot.nonce += 1
  })
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
    await element.requestFullscreen()
  } catch {
    ElMessage.warning('浏览器未允许全屏显示')
  }
}

function openPlayback() {
  window.history.pushState({}, '', '/recordings/browser')
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function openStreamConfig(cameraId: number | null) {
  const camera = cameraById(cameraId)
  if (!camera) return
  configCameraId.value = camera.id
  subPathDraft.value = camera.sub_rtsp_path || ''
  configVisible.value = true
}

async function saveSubPath() {
  const camera = cameraById(configCameraId.value)
  if (!camera) return
  savingSubPath.value = true
  try {
    const value = subPathDraft.value.trim()
    await axios.put(`/api/cameras/${camera.id}`, { sub_rtsp_path: value || null })
    camera.sub_rtsp_path = value || null
    slots.value.forEach((slot, index) => {
      if (slot.cameraId === camera.id) restartSlot(index)
    })
    ElMessage.success(value ? '子码流路径已保存并重新连接' : '已清除自定义子码流路径')
    configVisible.value = false
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '保存失败')
  } finally {
    savingSubPath.value = false
  }
}

function togglePause() {
  wallPaused.value = !wallPaused.value
  if (!wallPaused.value) {
    activeSlots.value.forEach((slot) => {
      slot.failed = false
      slot.loaded = false
      slot.nonce += 1
    })
  }
}

function onVisibilityChange() {
  if (document.hidden) wallPaused.value = true
  else if (wallPaused.value) {
    wallPaused.value = false
    activeSlots.value.forEach((slot) => {
      slot.failed = false
      slot.loaded = false
      slot.nonce += 1
    })
  }
}

watch(layoutCount, persistWall)

onMounted(() => {
  loadSavedWall()
  void loadData()
  statusTimer = window.setInterval(refreshStatus, 5000)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onBeforeUnmount(() => {
  if (statusTimer !== null) window.clearInterval(statusTimer)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <div class="wall-page" v-loading="loading">
    <header class="wall-header">
      <div>
        <div class="eyebrow">LIVE MONITORING</div>
        <h2>实时监控</h2>
        <p>Video Wall 默认优先子码流；布局越大自动降低预览分辨率与帧率，录像主链路不受影响。</p>
      </div>
      <div class="header-actions">
        <div class="profile-pill">{{ previewProfile.label }}</div>
        <el-button size="small" @click="togglePause">{{ wallPaused ? '恢复画面' : '暂停画面' }}</el-button>
        <el-button size="small" @click="autoFill">自动布局</el-button>
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
          <img
            v-if="previewUrl(slot)"
            :key="previewUrl(slot)"
            class="preview-image"
            :class="{ ready: slot.loaded }"
            :src="previewUrl(slot)"
            :alt="cameraById(slot.cameraId)?.name"
            @load="slot.loaded = true; slot.failed = false"
            @error="slot.failed = true; slot.loaded = false"
          />

          <div v-if="!slot.loaded && !slot.failed && !wallPaused" class="slot-loading">
            <span class="loader-ring"></span>
            <span>连接 {{ cameraById(slot.cameraId)?.name }}…</span>
          </div>

          <div v-if="wallPaused" class="slot-state-message">
            <VideoCamera />
            <strong>画面已暂停</strong>
            <span>恢复页面后会自动重新连接</span>
          </div>

          <div v-else-if="slot.failed" class="slot-state-message error">
            <VideoCamera />
            <strong>预览连接失败</strong>
            <span>{{ slot.stream === 'main' ? '请检查主码流或网络' : '可尝试切到主码流验证' }}</span>
            <el-button size="small" @click="restartSlot(index)">重新连接</el-button>
          </div>

          <div class="slot-topbar">
            <div class="camera-title">
              <span class="live-dot" :class="slot.failed ? 'error' : 'live'"></span>
              <strong>{{ cameraById(slot.cameraId)?.name }}</strong>
              <span>{{ cameraById(slot.cameraId)?.ip }}</span>
            </div>
            <div class="slot-badges">
              <span class="rec-badge" :class="stateClass(slot.cameraId)">{{ stateLabel(slot.cameraId) }}</span>
              <el-dropdown trigger="click" @command="(command: PreviewStream) => setStream(index, command)">
                <button class="stream-button">{{ slot.stream === 'main' ? 'MAIN' : slot.stream === 'sub' ? 'SUB' : 'AUTO' }}</button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="auto">自动 · 子码流优先</el-dropdown-item>
                    <el-dropdown-item command="sub">固定子码流</el-dropdown-item>
                    <el-dropdown-item command="main">固定主码流</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>

          <div class="slot-actions">
            <button title="重新连接" @click="restartSlot(index)"><RefreshRight /></button>
            <button title="子码流配置" @click="openStreamConfig(slot.cameraId)"><Setting /></button>
            <button title="进入录像回放" @click="openPlayback"><VideoPlay /></button>
            <button title="全屏" @click="enterFullscreen(index)"><FullScreen /></button>
            <button title="移除画面" @click="clearSlot(index)"><Close /></button>
          </div>

          <div class="slot-footer">
            <span>{{ streamLabel(slot.stream) }}</span>
            <span>{{ previewProfile.label }}</span>
          </div>
        </template>

        <button v-else class="empty-slot" @click="enabledCameras[index] && assignCamera(index, enabledCameras[index].id)">
          <span class="empty-icon"><VideoCamera /></span>
          <strong>拖入摄像头</strong>
          <span>或点击自动分配第 {{ index + 1 }} 路</span>
        </button>
      </article>
    </section>

    <div class="wall-note">
      <span><i class="note-dot green"></i>录像中</span>
      <span><i class="note-dot amber"></i>重连/启动中</span>
      <span><i class="note-dot gray"></i>未录像</span>
      <span>预览采用独立 FFmpeg，会在页面隐藏或离开实时监控时自动断开。</span>
    </div>

    <el-dialog v-model="configVisible" title="子码流配置" width="480px">
      <template v-if="cameraById(configCameraId)">
        <div class="config-camera">
          <strong>{{ cameraById(configCameraId)?.name }}</strong>
          <span>{{ cameraById(configCameraId)?.ip }}</span>
        </div>
        <el-form label-position="top">
          <el-form-item label="主码流 RTSP 路径">
            <el-input :model-value="cameraById(configCameraId)?.rtsp_path" disabled />
          </el-form-item>
          <el-form-item label="子码流 RTSP 路径">
            <el-input v-model="subPathDraft" placeholder="例如 /ch1/sub；留空时由后端尝试自动推测" clearable />
          </el-form-item>
        </el-form>
      </template>
      <template #footer>
        <el-button @click="configVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingSubPath" @click="saveSubPath">保存并重连</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.wall-page {
  min-height: calc(100vh - 140px);
  padding: 22px 24px 28px;
  background:
    radial-gradient(circle at 75% -20%, rgba(76, 141, 255, .075), transparent 34%),
    var(--nvr-bg);
}
.wall-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 16px;
}
.eyebrow { color: var(--nvr-blue); font-size: 9px; font-weight: 800; letter-spacing: .18em; }
h2 { margin: 4px 0 5px; font-size: 21px; font-weight: 680; letter-spacing: -.02em; }
p { margin: 0; color: var(--nvr-muted); font-size: 11px; }
.header-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.profile-pill {
  height: 28px;
  display: inline-flex;
  align-items: center;
  padding: 0 9px;
  color: #91a0b3;
  background: rgba(255,255,255,.03);
  border: 1px solid var(--nvr-border);
  border-radius: 6px;
  font-size: 10px;
}
.wall-toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 12px;
  padding: 9px 10px;
  border: 1px solid var(--nvr-border);
  border-radius: 8px;
  background: rgba(18, 24, 33, .76);
}
.layout-switcher {
  flex: 0 0 auto;
  display: flex;
  padding: 2px;
  border-radius: 6px;
  background: #0a0e13;
  border: 1px solid rgba(255,255,255,.05);
}
.layout-switcher button {
  width: 32px;
  height: 27px;
  border: 0;
  border-radius: 4px;
  color: #66758a;
  background: transparent;
  cursor: pointer;
  font-size: 11px;
  font-weight: 700;
}
.layout-switcher button:hover { color: #c6d0dc; }
.layout-switcher button.active { color: white; background: #25354b; box-shadow: inset 0 0 0 1px rgba(76,141,255,.28); }
.camera-tray { min-width: 0; display: flex; align-items: center; gap: 7px; overflow-x: auto; scrollbar-width: none; }
.camera-tray::-webkit-scrollbar { display: none; }
.tray-label { flex: 0 0 auto; padding: 0 4px; color: #647286; font-size: 10px; }
.camera-chip {
  flex: 0 0 auto;
  min-width: 108px;
  height: 34px;
  display: grid;
  grid-template-columns: 7px auto;
  grid-template-rows: 15px 11px;
  column-gap: 7px;
  align-items: center;
  padding: 3px 9px;
  color: #c0cad6;
  text-align: left;
  border: 1px solid rgba(255,255,255,.06);
  border-radius: 6px;
  background: rgba(255,255,255,.022);
  cursor: grab;
}
.camera-chip:hover { border-color: rgba(76,141,255,.28); background: rgba(76,141,255,.05); }
.camera-chip.assigned { border-color: rgba(76,141,255,.22); background: rgba(76,141,255,.055); }
.camera-chip.disabled { opacity: .4; cursor: not-allowed; }
.camera-chip > span:nth-child(2) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; font-weight: 650; }
.camera-chip small { grid-column: 2; color: #637185; font-size: 8px; }
.chip-dot { grid-row: 1 / 3; width: 6px; height: 6px; border-radius: 50%; }
.chip-dot.recording { background: var(--nvr-green); box-shadow: 0 0 0 3px rgba(46,204,138,.08); }
.chip-dot.warning { background: var(--nvr-yellow); }
.chip-dot.idle { background: #526073; }
.video-wall {
  display: grid;
  gap: 4px;
  width: 100%;
  background: #06080b;
  border: 1px solid rgba(255,255,255,.06);
  border-radius: 9px;
  padding: 4px;
  overflow: hidden;
}
.video-wall.grid-1 { grid-template-columns: 1fr; }
.video-wall.grid-4 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.video-wall.grid-9 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.wall-slot {
  position: relative;
  min-width: 0;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  background: #0a0d11;
  border-radius: 5px;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.035);
}
.grid-1 .wall-slot { max-height: calc(100vh - 255px); margin: 0 auto; width: 100%; }
.wall-slot::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  box-shadow: inset 0 0 42px rgba(0,0,0,.22);
}
.wall-slot.failed { box-shadow: inset 0 0 0 1px rgba(240,93,94,.35); }
.preview-image { width: 100%; height: 100%; object-fit: contain; display: block; opacity: 0; transition: opacity .2s ease; background: black; }
.preview-image.ready { opacity: 1; }
.slot-topbar {
  position: absolute;
  z-index: 4;
  inset: 0 0 auto 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  padding: 5px 8px;
  background: linear-gradient(180deg, rgba(5,7,10,.82), rgba(5,7,10,.08));
}
.camera-title { min-width: 0; display: flex; align-items: center; gap: 7px; }
.camera-title strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; font-weight: 650; color: #edf3fa; }
.camera-title > span:last-child { color: #758399; font-size: 8px; }
.live-dot { flex: 0 0 auto; width: 6px; height: 6px; border-radius: 50%; }
.live-dot.live { background: var(--nvr-green); box-shadow: 0 0 0 3px rgba(46,204,138,.09); }
.live-dot.error { background: var(--nvr-red); }
.slot-badges { display: flex; align-items: center; gap: 5px; }
.rec-badge, .stream-button {
  height: 20px;
  display: inline-flex;
  align-items: center;
  padding: 0 6px;
  border-radius: 4px;
  font-size: 8px;
  font-weight: 750;
  letter-spacing: .04em;
}
.rec-badge.recording { color: #68dca8; background: rgba(46,204,138,.11); }
.rec-badge.warning { color: #f2c262; background: rgba(245,185,66,.11); }
.rec-badge.idle { color: #7e8b9c; background: rgba(255,255,255,.05); }
.stream-button { border: 1px solid rgba(255,255,255,.07); color: #94a2b4; background: rgba(8,11,15,.56); cursor: pointer; }
.stream-button:hover { color: white; border-color: rgba(76,141,255,.3); }
.slot-actions {
  position: absolute;
  z-index: 5;
  right: 7px;
  bottom: 7px;
  display: flex;
  gap: 4px;
  opacity: 0;
  transform: translateY(3px);
  transition: .16s ease;
}
.wall-slot:hover .slot-actions { opacity: 1; transform: none; }
.slot-actions button {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 5px;
  color: #c8d2de;
  background: rgba(8,11,15,.76);
  backdrop-filter: blur(10px);
  cursor: pointer;
}
.slot-actions button:hover { color: white; background: rgba(76,141,255,.22); border-color: rgba(76,141,255,.3); }
.slot-actions :deep(svg) { width: 13px; }
.slot-footer {
  position: absolute;
  z-index: 3;
  left: 8px;
  bottom: 7px;
  display: flex;
  gap: 8px;
  color: rgba(186,199,214,.62);
  font-size: 8px;
  opacity: 0;
  transition: .15s ease;
}
.wall-slot:hover .slot-footer { opacity: 1; }
.slot-loading, .slot-state-message {
  position: absolute;
  z-index: 2;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  color: #647286;
  background: radial-gradient(circle, #111822, #090c10 70%);
  font-size: 9px;
}
.loader-ring { width: 18px; height: 18px; border: 2px solid #253041; border-top-color: var(--nvr-blue); border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.slot-state-message :deep(svg) { width: 25px; color: #49576a; }
.slot-state-message strong { color: #99a7b9; font-size: 11px; }
.slot-state-message span { color: #59687c; font-size: 9px; }
.slot-state-message.error :deep(svg), .slot-state-message.error strong { color: #d86a6b; }
.empty-slot { width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; color: #4f5b6b; background: transparent; border: 1px dashed transparent; cursor: pointer; }
.empty-slot:hover { color: #7d8da1; border-color: rgba(76,141,255,.22); background: rgba(76,141,255,.025); }
.empty-icon { width: 33px; height: 33px; display: grid; place-items: center; border-radius: 8px; background: rgba(255,255,255,.025); }
.empty-icon :deep(svg) { width: 17px; }
.empty-slot strong { font-size: 10px; font-weight: 600; }
.empty-slot > span:last-child { font-size: 8px; }
.wall-note { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; padding: 9px 4px 0; color: #5e6b7e; font-size: 9px; }
.wall-note span { display: flex; align-items: center; gap: 5px; }
.note-dot { width: 6px; height: 6px; border-radius: 50%; }
.note-dot.green { background: var(--nvr-green); }
.note-dot.amber { background: var(--nvr-yellow); }
.note-dot.gray { background: #526073; }
.config-camera { display: flex; justify-content: space-between; align-items: center; margin: -4px 0 18px; padding: 9px 11px; border-radius: 7px; background: rgba(255,255,255,.025); }
.config-camera strong { font-size: 12px; }
.config-camera span { color: var(--nvr-muted); font-size: 10px; }
.wall-slot:fullscreen { width: 100vw; height: 100vh; aspect-ratio: auto; border-radius: 0; background: black; }
.wall-slot:fullscreen .preview-image { object-fit: contain; }
.wall-slot:fullscreen .slot-actions, .wall-slot:fullscreen .slot-footer { opacity: 1; }
@media (max-width: 960px) {
  .wall-page { padding: 16px; }
  .wall-header { flex-direction: column; }
  .header-actions { justify-content: flex-start; }
  .video-wall.grid-9 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 620px) {
  .wall-page { padding: 12px; }
  .wall-toolbar { align-items: flex-start; flex-direction: column; }
  .camera-tray { width: 100%; }
  .video-wall.grid-4, .video-wall.grid-9 { grid-template-columns: 1fr; }
  .camera-title > span:last-child, .slot-footer { display: none; }
}
</style>
