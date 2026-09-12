<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowLeft,
  ArrowRight,
  Connection,
  Delete,
  Edit,
  Plus,
  Refresh,
  Search,
  VideoCamera,
  VideoPause,
  VideoPlay,
} from '@element-plus/icons-vue'
import CameraDeviceGlyph from './CameraDeviceGlyph.vue'

type CameraFormFactor = 'unknown' | 'bullet' | 'dome' | 'turret' | 'ptz' | 'doorbell' | 'indoor'
type PreviewSource = 'main' | 'sub'
type FilterKey = 'all' | 'online' | 'issue' | 'recording'
type SortKey = 'attention' | 'name' | 'ip' | 'status'
type CameraHealth = 'online' | 'offline' | 'unknown' | 'disabled'
type HistoryMode = 'push' | 'replace'

interface Camera {
  id: number
  name: string
  manufacturer?: string | null
  model?: string | null
  form_factor: CameraFormFactor
  ip: string
  rtsp_port: number
  username: string
  rtsp_path: string
  sub_rtsp_path?: string | null
  enabled: boolean
  auto_record: boolean
  recording_schedule_enabled: boolean
  timestamp_mode: 'native' | 'reconstruct' | 'wallclock'
  password_set?: boolean
  video_codec?: string | null
  width?: number | null
  height?: number | null
  fps_num?: number | null
  fps_den?: number | null
  audio_codec?: string | null
  status: string
  connectivity_status: string
  recorder_state: string
  schedule_state: string
  last_probe_at?: string | null
  last_online_at?: string | null
}

const emit = defineEmits<{
  (event: 'open-batch'): void
  (event: 'open-preview'): void
}>()

const cameras = ref<Camera[]>([])
const loading = ref(false)
const query = ref('')
const filter = ref<FilterKey>('all')
const sortKey = ref<SortKey>('attention')
const drawerVisible = ref(false)
const selectedCamera = ref<Camera | null>(null)
const previewPlaying = ref(false)
const previewFailed = ref(false)
const previewNonce = ref(Date.now())
const previewSource = ref<PreviewSource>('main')
const previewFallbackUsed = ref(false)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const actionCameraId = ref<number | null>(null)
let refreshTimer: number | null = null

const form = reactive({
  name: '',
  manufacturer: '',
  model: '',
  form_factor: 'unknown' as CameraFormFactor,
  ip: '',
  rtsp_port: 554,
  username: 'admin',
  password: '',
  rtsp_path: '/ch1/main',
  sub_rtsp_path: '',
  timestamp_mode: 'reconstruct' as Camera['timestamp_mode'],
  enabled: true,
  auto_record: false,
})

const formFactorOptions: Array<{ value: CameraFormFactor; label: string }> = [
  { value: 'unknown', label: '未指定' },
  { value: 'bullet', label: '枪机' },
  { value: 'dome', label: '半球' },
  { value: 'turret', label: '炮塔 / 海螺' },
  { value: 'ptz', label: '云台 PTZ' },
  { value: 'doorbell', label: '门铃' },
  { value: 'indoor', label: '室内桌面机' },
]

const sortOptions: Array<{ value: SortKey; label: string }> = [
  { value: 'attention', label: '异常优先' },
  { value: 'name', label: '按名称' },
  { value: 'ip', label: '按 IP' },
  { value: 'status', label: '按状态' },
]

function apiError(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
    return error.message || fallback
  }
  return fallback
}

function cameraById(cameraId: number) {
  return cameras.value.find((item) => item.id === cameraId)
}

function runtimeState(cameraId: number) {
  return cameraById(cameraId)?.recorder_state || 'STOPPED'
}

function isRecording(cameraId: number) {
  return runtimeState(cameraId) === 'RECORDING'
}

function health(camera: Camera): CameraHealth {
  if (!camera.enabled) return 'disabled'
  if (camera.connectivity_status === 'online') return 'online'
  if (camera.connectivity_status === 'offline') return 'offline'
  return 'unknown'
}

function healthLabel(camera: Camera) {
  const value = health(camera)
  if (value === 'online') return '在线'
  if (value === 'offline') return '离线'
  if (value === 'disabled') return '已禁用'
  return '未检测'
}

function runtimeLabel(camera: Camera) {
  const state = camera.recorder_state || 'STOPPED'
  if (state === 'RECORDING') return '录像中'
  if (state === 'STARTING') return '启动中'
  if (state === 'RECONNECTING') return '重连中'
  if (state === 'STOPPING') return '停止中'
  return '未录像'
}

function formFactorLabel(value?: CameraFormFactor | null) {
  return formFactorOptions.find((item) => item.value === value)?.label || '未指定'
}

function identitySummary(camera: Camera) {
  const parts = [camera.manufacturer, camera.model, camera.form_factor !== 'unknown' ? formFactorLabel(camera.form_factor) : null]
    .filter((item): item is string => Boolean(item))
  return parts.length ? parts.join(' · ') : '设备信息未补充'
}

function fps(camera: Camera) {
  if (!camera.fps_num || !camera.fps_den) return null
  const value = camera.fps_num / camera.fps_den
  return Number.isInteger(value) ? `${value}` : value.toFixed(2)
}

function videoSummary(camera: Camera) {
  const parts: string[] = []
  if (camera.video_codec) parts.push(camera.video_codec.toUpperCase())
  if (camera.width && camera.height) parts.push(`${camera.width}×${camera.height}`)
  const frameRate = fps(camera)
  if (frameRate) parts.push(`${frameRate} FPS`)
  return parts.length ? parts.join(' · ') : '尚未获取视频参数'
}

function schedulePolicyLabel(camera: Camera) {
  if (!camera.auto_record) return '手动录像'
  if (camera.recording_schedule_enabled) return '按计划录像'
  return '自动录像'
}

function scheduleStateLabel(camera: Camera) {
  const state = camera.schedule_state
  if (state === 'manual_override') return '手动接管'
  if (state === 'manual_paused') return '手动暂停'
  if (state === 'in_window') return '计划时段内'
  if (state === 'scheduled') return '等待计划'
  if (state === 'automatic') return '全天自动'
  if (state === 'global_disabled') return '全局自动关闭'
  if (state === 'probe_required') return '需要检测'
  if (state === 'error') return '计划异常'
  return '未启用'
}

function formatTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function compareCameraNames(left: Camera, right: Camera) {
  return left.name.localeCompare(right.name, 'zh-CN', { numeric: true, sensitivity: 'base' }) || left.id - right.id
}

function ipParts(camera: Camera) {
  return camera.ip.split('.').map((part) => {
    const value = Number(part)
    return Number.isInteger(value) && value >= 0 && value <= 255 ? value : null
  })
}

function compareCameraIps(left: Camera, right: Camera) {
  const leftParts = ipParts(left)
  const rightParts = ipParts(right)
  if (leftParts.length === 4 && rightParts.length === 4 && leftParts.every((part) => part !== null) && rightParts.every((part) => part !== null)) {
    for (let index = 0; index < 4; index += 1) {
      const difference = (leftParts[index] as number) - (rightParts[index] as number)
      if (difference !== 0) return difference
    }
  } else {
    const textDifference = left.ip.localeCompare(right.ip, undefined, { numeric: true, sensitivity: 'base' })
    if (textDifference !== 0) return textDifference
  }
  return left.rtsp_port - right.rtsp_port || compareCameraNames(left, right)
}

function statusRank(camera: Camera) {
  const state = health(camera)
  if (state === 'offline') return 0
  if (state === 'unknown') return 1
  if (state === 'online') return 2
  return 3
}

function attentionRank(camera: Camera) {
  const state = health(camera)
  if (state === 'offline') return 0
  if (state === 'unknown') return 1
  if (camera.schedule_state === 'error' || camera.schedule_state === 'probe_required' || camera.recorder_state === 'RECONNECTING') return 2
  if (camera.recorder_state === 'RECORDING') return 3
  if (state === 'online') return 4
  return 5
}

function compareCameras(left: Camera, right: Camera) {
  if (sortKey.value === 'name') return compareCameraNames(left, right)
  if (sortKey.value === 'ip') return compareCameraIps(left, right)
  if (sortKey.value === 'status') {
    return statusRank(left) - statusRank(right)
      || Number(right.recorder_state === 'RECORDING') - Number(left.recorder_state === 'RECORDING')
      || compareCameraNames(left, right)
  }
  return attentionRank(left) - attentionRank(right) || compareCameraNames(left, right)
}

function inferSubstreamPath(mainPath: string) {
  if (mainPath.includes('/main')) {
    const index = mainPath.lastIndexOf('/main')
    return `${mainPath.slice(0, index)}/sub${mainPath.slice(index + 5)}`
  }
  if (mainPath.endsWith('main')) return `${mainPath.slice(0, -4)}sub`
  return null
}

function preferredPreviewSource(camera: Camera): PreviewSource {
  return camera.sub_rtsp_path?.trim() || inferSubstreamPath(camera.rtsp_path) ? 'sub' : 'main'
}

function preparePreview(camera: Camera) {
  previewPlaying.value = false
  previewSource.value = preferredPreviewSource(camera)
  previewFallbackUsed.value = false
  previewFailed.value = false
  previewNonce.value = Date.now()
}

function startPreview() {
  if (!selectedCamera.value?.enabled) return
  previewSource.value = preferredPreviewSource(selectedCamera.value)
  previewFallbackUsed.value = false
  previewFailed.value = false
  previewNonce.value = Date.now()
  previewPlaying.value = true
}

function stopPreview() {
  previewPlaying.value = false
  previewFailed.value = false
  previewFallbackUsed.value = false
}

function refreshPreview() {
  if (!selectedCamera.value?.enabled) return
  previewSource.value = preferredPreviewSource(selectedCamera.value)
  previewFallbackUsed.value = false
  previewFailed.value = false
  previewNonce.value = Date.now()
  previewPlaying.value = true
}

function handlePreviewLoad() {
  previewFailed.value = false
}

function handlePreviewError() {
  if (!selectedCamera.value || !previewPlaying.value) return
  if (previewSource.value === 'sub') {
    previewSource.value = 'main'
    previewFallbackUsed.value = true
    previewFailed.value = false
    previewNonce.value = Date.now()
    return
  }
  previewFailed.value = true
  previewPlaying.value = false
}

function deepLinkedCameraId() {
  const raw = new URLSearchParams(window.location.search).get('camera_id')
  if (!raw) return null
  const cameraId = Number(raw)
  return Number.isInteger(cameraId) && cameraId > 0 ? cameraId : null
}

function writeCameraDeepLink(cameraId: number | null, mode: HistoryMode) {
  const url = new URL(window.location.href)
  if (cameraId === null) url.searchParams.delete('camera_id')
  else url.searchParams.set('camera_id', String(cameraId))
  const next = `${url.pathname}${url.search}${url.hash}`
  if (mode === 'push') window.history.pushState({}, '', next)
  else window.history.replaceState({}, '', next)
}

function syncDrawerFromLocation(showMissing = false) {
  const cameraId = deepLinkedCameraId()
  if (cameraId === null) {
    if (drawerVisible.value) drawerVisible.value = false
    selectedCamera.value = null
    previewPlaying.value = false
    return
  }
  const camera = cameraById(cameraId)
  if (!camera) {
    if (showMissing) ElMessage.warning(`未找到摄像头 #${cameraId}`)
    writeCameraDeepLink(null, 'replace')
    drawerVisible.value = false
    selectedCamera.value = null
    previewPlaying.value = false
    return
  }
  const openingDifferentCamera = !drawerVisible.value || selectedCamera.value?.id !== camera.id
  selectedCamera.value = camera
  if (openingDifferentCamera) preparePreview(camera)
  if (!camera.enabled) previewPlaying.value = false
  drawerVisible.value = true
}

function handleCameraPopState() {
  syncDrawerFromLocation(false)
}

const summary = computed(() => ({
  total: cameras.value.length,
  online: cameras.value.filter((camera) => health(camera) === 'online').length,
  issue: cameras.value.filter((camera) => ['offline', 'unknown'].includes(health(camera))).length,
  recording: cameras.value.filter((camera) => isRecording(camera.id)).length,
}))

const sortedCameras = computed(() => [...cameras.value].sort(compareCameras))

const filteredCameras = computed(() => {
  const needle = query.value.trim().toLowerCase()
  return sortedCameras.value.filter((camera) => {
    const matched = !needle || [
      camera.name,
      camera.manufacturer || '',
      camera.model || '',
      camera.ip,
      camera.rtsp_path,
      camera.sub_rtsp_path || '',
    ].some((value) => value.toLowerCase().includes(needle))
    if (!matched) return false
    if (filter.value === 'online') return health(camera) === 'online'
    if (filter.value === 'issue') return ['offline', 'unknown'].includes(health(camera))
    if (filter.value === 'recording') return isRecording(camera.id)
    return true
  })
})

const selectedInFilteredCameras = computed(() => Boolean(
  selectedCamera.value && filteredCameras.value.some((camera) => camera.id === selectedCamera.value?.id),
))

const navigationCameras = computed(() => {
  if (!selectedCamera.value || selectedInFilteredCameras.value) return filteredCameras.value
  return sortedCameras.value
})

const selectedNavigationIndex = computed(() => {
  if (!selectedCamera.value) return -1
  return navigationCameras.value.findIndex((camera) => camera.id === selectedCamera.value?.id)
})

const previousCamera = computed<Camera | null>(() => {
  const index = selectedNavigationIndex.value
  return index > 0 ? navigationCameras.value[index - 1] : null
})

const nextCamera = computed<Camera | null>(() => {
  const index = selectedNavigationIndex.value
  return index >= 0 && index < navigationCameras.value.length - 1 ? navigationCameras.value[index + 1] : null
})

const navigationScopeLabel = computed(() => {
  if (!selectedInFilteredCameras.value) return '全部设备'
  if (query.value.trim() || filter.value !== 'all') return '当前筛选'
  return '全部设备'
})

const previewSrc = computed(() => selectedCamera.value && previewPlaying.value
  ? `/api/cameras/${selectedCamera.value.id}/preview.mjpeg?stream=${previewSource.value}&fps=6&width=960&_=${previewNonce.value}`
  : '')

async function loadData(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    const { data } = await axios.get<Camera[]>('/api/cameras')
    cameras.value = data
    const requestedId = deepLinkedCameraId()
    if (requestedId !== null) {
      syncDrawerFromLocation(showLoading)
    } else if (selectedCamera.value) {
      selectedCamera.value = cameras.value.find((item) => item.id === selectedCamera.value?.id) || null
      if (!selectedCamera.value) drawerVisible.value = false
      else if (!selectedCamera.value.enabled) previewPlaying.value = false
    }
  } catch (error) {
    if (showLoading) ElMessage.error(apiError(error, '摄像头数据加载失败'))
  } finally {
    if (showLoading) loading.value = false
  }
}

function resetForm() {
  editingId.value = null
  Object.assign(form, {
    name: '',
    manufacturer: '',
    model: '',
    form_factor: 'unknown',
    ip: '',
    rtsp_port: 554,
    username: 'admin',
    password: '',
    rtsp_path: '/ch1/main',
    sub_rtsp_path: '',
    timestamp_mode: 'reconstruct',
    enabled: true,
    auto_record: false,
  })
}

function openCreate() {
  resetForm()
  dialogVisible.value = true
}

function openEdit(camera: Camera) {
  editingId.value = camera.id
  Object.assign(form, {
    name: camera.name,
    manufacturer: camera.manufacturer || '',
    model: camera.model || '',
    form_factor: camera.form_factor || 'unknown',
    ip: camera.ip,
    rtsp_port: camera.rtsp_port,
    username: camera.username,
    password: '',
    rtsp_path: camera.rtsp_path,
    sub_rtsp_path: camera.sub_rtsp_path || '',
    timestamp_mode: camera.timestamp_mode,
    enabled: camera.enabled,
    auto_record: camera.auto_record,
  })
  dialogVisible.value = true
}

async function saveCamera() {
  if (!form.name.trim() || !form.ip.trim() || !form.rtsp_path.trim()) {
    ElMessage.warning('请填写摄像头名称、IP 和主码流路径')
    return
  }
  if (editingId.value === null && !form.password) {
    ElMessage.warning('新增摄像头时必须填写密码')
    return
  }

  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      name: form.name.trim(),
      manufacturer: form.manufacturer.trim() || null,
      model: form.model.trim() || null,
      form_factor: form.form_factor,
      ip: form.ip.trim(),
      rtsp_port: form.rtsp_port,
      username: form.username.trim(),
      rtsp_path: form.rtsp_path.trim(),
      sub_rtsp_path: form.sub_rtsp_path.trim() || null,
      timestamp_mode: form.timestamp_mode,
      enabled: form.enabled,
      auto_record: form.auto_record,
    }
    if (form.password) payload.password = form.password

    if (editingId.value === null) {
      await axios.post('/api/cameras', payload)
      ElMessage.success('摄像头已添加')
    } else {
      await axios.put(`/api/cameras/${editingId.value}`, payload)
      ElMessage.success('摄像头配置已保存')
    }
    dialogVisible.value = false
    resetForm()
    await loadData()
  } catch (error) {
    ElMessage.error(apiError(error, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function runAction(camera: Camera, action: 'probe' | 'start' | 'stop') {
  actionCameraId.value = camera.id
  try {
    if (action === 'probe') {
      const { data } = await axios.post(`/api/cameras/${camera.id}/probe`)
      const detectedFps = typeof data.fps === 'number' ? `${data.fps.toFixed(2)} FPS` : 'FPS -'
      ElMessage.success(`${camera.name}：${data.video_codec || '-'} ${data.width || '-'}×${data.height || '-'} · ${detectedFps}`)
    } else if (action === 'start') {
      await axios.post(`/api/cameras/${camera.id}/start`)
      ElMessage.success(`${camera.name} 已开始录像`)
    } else {
      await axios.post(`/api/cameras/${camera.id}/stop`)
      ElMessage.success(`${camera.name} 已停止录像`)
    }
    await loadData(false)
  } catch (error) {
    ElMessage.error(apiError(error, action === 'probe' ? '连接检测失败' : '操作失败'))
  } finally {
    actionCameraId.value = null
  }
}

async function removeCamera(camera: Camera) {
  try {
    await ElMessageBox.confirm(
      `确认删除“${camera.name}”？正在录像时会先停止录像。`,
      '删除摄像头',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await axios.delete(`/api/cameras/${camera.id}`)
    ElMessage.success('摄像头已删除')
    if (selectedCamera.value?.id === camera.id) {
      previewPlaying.value = false
      drawerVisible.value = false
      writeCameraDeepLink(null, 'replace')
    }
    await loadData()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiError(error, '删除失败'))
  }
}

function openDetails(camera: Camera, syncUrl = true) {
  const openingDifferentCamera = selectedCamera.value?.id !== camera.id || !drawerVisible.value
  selectedCamera.value = camera
  if (openingDifferentCamera) preparePreview(camera)
  drawerVisible.value = true
  if (syncUrl && deepLinkedCameraId() !== camera.id) writeCameraDeepLink(camera.id, 'push')
}

function switchDetails(camera: Camera | null) {
  if (!camera) return
  openDetails(camera, false)
  writeCameraDeepLink(camera.id, 'replace')
}

function closeDrawer() {
  const selectedId = selectedCamera.value?.id || null
  previewPlaying.value = false
  selectedCamera.value = null
  previewFailed.value = false
  previewFallbackUsed.value = false
  if (selectedId !== null && deepLinkedCameraId() === selectedId) writeCameraDeepLink(null, 'replace')
}

onMounted(() => {
  window.addEventListener('popstate', handleCameraPopState)
  void loadData()
  refreshTimer = window.setInterval(() => void loadData(false), 10000)
})

onBeforeUnmount(() => {
  previewPlaying.value = false
  if (refreshTimer !== null) window.clearInterval(refreshTimer)
  window.removeEventListener('popstate', handleCameraPopState)
})
</script>

<template>
  <section class="camera-page" v-loading="loading">
    <div class="page-heading">
      <div>
        <h1>摄像头设备</h1>
        <p>集中查看设备身份、连接能力、实时预览与录像运行状态。</p>
      </div>
      <div class="heading-actions">
        <el-button :icon="Refresh" @click="loadData()">刷新</el-button>
        <el-button @click="emit('open-batch')">批量添加</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">添加摄像头</el-button>
      </div>
    </div>

    <div class="summary-grid">
      <button class="summary-card" :class="{ active: filter === 'all' }" @click="filter = 'all'">
        <span>全部摄像头</span><strong>{{ summary.total }}</strong><small>已配置设备</small>
      </button>
      <button class="summary-card online" :class="{ active: filter === 'online' }" @click="filter = 'online'">
        <span>在线</span><strong>{{ summary.online }}</strong><small>最近连接正常</small>
      </button>
      <button class="summary-card issue" :class="{ active: filter === 'issue' }" @click="filter = 'issue'">
        <span>异常 / 未检测</span><strong>{{ summary.issue }}</strong><small>建议执行连接检测</small>
      </button>
      <button class="summary-card recording" :class="{ active: filter === 'recording' }" @click="filter = 'recording'">
        <span>录像中</span><strong>{{ summary.recording }}</strong><small>当前录像进程</small>
      </button>
    </div>

    <div class="toolbar">
      <el-input v-model="query" clearable :prefix-icon="Search" placeholder="搜索名称、厂商、型号、IP 或 RTSP 路径" class="search-box" />
      <el-select v-model="sortKey" class="camera-sort-select" aria-label="设备排序" title="设备排序">
        <el-option v-for="item in sortOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <span class="result-count">显示 {{ filteredCameras.length }} / {{ cameras.length }} 台</span>
    </div>

    <div v-if="filteredCameras.length" class="camera-list">
      <article
        v-for="camera in filteredCameras"
        :key="camera.id"
        class="camera-card"
        :class="{ selected: drawerVisible && selectedCamera?.id === camera.id }"
        role="button"
        tabindex="0"
        :aria-label="`查看 ${camera.name} 详情`"
        @click="openDetails(camera)"
        @keydown.enter.prevent="openDetails(camera)"
        @keydown.space.prevent="openDetails(camera)"
      >
        <div class="camera-card-topline">
          <div class="camera-icon" :class="health(camera)" :title="formFactorLabel(camera.form_factor)">
            <CameraDeviceGlyph :form-factor="camera.form_factor" />
          </div>
          <span class="camera-card-id">#{{ camera.id }}</span>
        </div>

        <div class="camera-copy">
          <div class="camera-name-row">
            <strong :title="camera.name">{{ camera.name }}</strong>
            <span class="health-badge" :class="health(camera)"><i></i>{{ healthLabel(camera) }}</span>
            <span class="record-badge" :class="{ active: isRecording(camera.id) }"><i></i>{{ runtimeLabel(camera) }}</span>
          </div>
          <div class="camera-identity" :title="identitySummary(camera)">{{ identitySummary(camera) }}</div>
          <div class="camera-video" :title="videoSummary(camera)">{{ videoSummary(camera) }}</div>
          <div class="camera-address" :title="`${camera.ip}:${camera.rtsp_port} · ${camera.rtsp_path}`">{{ camera.ip }}:{{ camera.rtsp_port }} · {{ camera.rtsp_path }}</div>
        </div>

        <div class="camera-signals">
          <div><span>录像策略</span><b>{{ schedulePolicyLabel(camera) }}</b></div>
          <div><span>计划状态</span><b>{{ scheduleStateLabel(camera) }}</b></div>
          <div><span>子码流</span><b>{{ camera.sub_rtsp_path ? '已配置' : inferSubstreamPath(camera.rtsp_path) ? '可推测' : '未配置' }}</b></div>
        </div>

        <div class="camera-card-footer">
          <span>点击查看预览与设备操作</span>
          <b>查看详情 →</b>
        </div>
      </article>
    </div>

    <div v-else class="empty-state">
      <VideoCamera />
      <strong>{{ cameras.length ? '没有符合条件的摄像头' : '还没有摄像头' }}</strong>
      <span>{{ cameras.length ? '调整搜索词或筛选条件。' : '添加第一台 RTSP 摄像头开始录像。' }}</span>
      <el-button v-if="!cameras.length" type="primary" :icon="Plus" @click="openCreate">添加摄像头</el-button>
    </div>

    <el-drawer v-model="drawerVisible" size="680px" class="camera-detail-drawer" @closed="closeDrawer">
      <template #header>
        <div v-if="selectedCamera" class="drawer-title">
          <div class="drawer-title-copy">
            <strong :title="selectedCamera.name">{{ selectedCamera.name }}</strong>
            <span :title="identitySummary(selectedCamera)">{{ identitySummary(selectedCamera) }}</span>
          </div>
          <div class="drawer-title-states">
            <span class="health-badge" :class="health(selectedCamera)"><i></i>{{ healthLabel(selectedCamera) }}</span>
            <span class="record-badge" :class="{ active: isRecording(selectedCamera.id) }"><i></i>{{ runtimeLabel(selectedCamera) }}</span>
          </div>
        </div>
      </template>

      <div v-if="selectedCamera" class="drawer-body drawer-body-v2">
        <nav v-if="navigationCameras.length > 1" class="drawer-device-nav" aria-label="摄像头切换">
          <el-button
            text
            :icon="ArrowLeft"
            :disabled="!previousCamera"
            :title="previousCamera ? `上一台：${previousCamera.name}` : '已经是第一台'"
            @click="switchDetails(previousCamera)"
          >上一台</el-button>
          <div class="drawer-device-nav-position">
            <strong>{{ selectedNavigationIndex + 1 }} / {{ navigationCameras.length }}</strong>
            <span>{{ navigationScopeLabel }}</span>
          </div>
          <el-button
            text
            :icon="ArrowRight"
            :disabled="!nextCamera"
            :title="nextCamera ? `下一台：${nextCamera.name}` : '已经是最后一台'"
            @click="switchDetails(nextCamera)"
          >下一台</el-button>
        </nav>

        <section class="device-overview">
          <div class="device-overview-visual" :class="health(selectedCamera)">
            <CameraDeviceGlyph :form-factor="selectedCamera.form_factor" />
          </div>
          <div class="device-overview-main">
            <div class="device-overview-heading">
              <div>
                <strong :title="selectedCamera.manufacturer || '通用 RTSP 摄像头'">{{ selectedCamera.manufacturer || '通用 RTSP 摄像头' }}</strong>
                <span :title="`${selectedCamera.model || formFactorLabel(selectedCamera.form_factor)} · #${selectedCamera.id}`">{{ selectedCamera.model || formFactorLabel(selectedCamera.form_factor) }} · #{{ selectedCamera.id }}</span>
              </div>
              <span class="device-overview-type">{{ formFactorLabel(selectedCamera.form_factor) }}</span>
            </div>
            <dl class="device-overview-facts">
              <div><dt>地址</dt><dd :title="`${selectedCamera.ip}:${selectedCamera.rtsp_port}`">{{ selectedCamera.ip }}:{{ selectedCamera.rtsp_port }}</dd></div>
              <div><dt>视频</dt><dd :title="videoSummary(selectedCamera)">{{ videoSummary(selectedCamera) }}</dd></div>
              <div><dt>最近在线</dt><dd>{{ formatTime(selectedCamera.last_online_at) }}</dd></div>
            </dl>
          </div>
        </section>

        <section class="preview-section">
          <div class="preview-section-heading">
            <div>
              <strong>实时预览</strong>
              <span>按需播放，打开详情不会自动拉取摄像头码流。</span>
            </div>
            <span v-if="previewPlaying" class="preview-live-badge"><i></i>预览中</span>
          </div>

          <div class="preview-panel preview-panel-v2" :class="{ idle: !previewPlaying && !previewFailed, failed: previewFailed }">
            <img
              v-if="selectedCamera.enabled && previewPlaying && !previewFailed"
              :key="previewNonce"
              class="preview-image"
              :src="previewSrc"
              :alt="`${selectedCamera.name} 实时预览`"
              @load="handlePreviewLoad"
              @error="handlePreviewError"
            />

            <div v-else-if="!selectedCamera.enabled" class="preview-empty preview-state-panel">
              <VideoCamera />
              <strong>摄像头已禁用</strong>
              <span>启用设备后才能播放实时画面。</span>
            </div>

            <div v-else-if="previewFailed" class="preview-empty preview-state-panel">
              <VideoCamera />
              <strong>实时预览暂不可用</strong>
              <span>子码流与主码流均无法打开，可先执行连接检测。</span>
              <el-button size="small" :icon="Refresh" @click="startPreview">重新尝试</el-button>
            </div>

            <button v-else type="button" class="preview-play-control" @click="startPreview">
              <span class="preview-play-icon"><VideoPlay /></span>
              <strong>播放实时画面</strong>
              <small>点击后才开始拉取 {{ preferredPreviewSource(selectedCamera) === 'sub' ? '子码流' : '主码流' }}</small>
            </button>

            <div v-if="previewPlaying && !previewFailed" class="preview-overlay preview-overlay-v2">
              <div class="preview-overlay-status">
                <span><i :class="{ active: isRecording(selectedCamera.id) }"></i>{{ runtimeLabel(selectedCamera) }}</span>
                <span class="preview-stream-chip" :class="{ fallback: previewFallbackUsed }">
                  {{ previewSource === 'sub' ? '子码流' : '主码流' }}<template v-if="previewFallbackUsed"> · 已回退</template>
                </span>
              </div>
              <div class="preview-overlay-actions">
                <button type="button" @click="refreshPreview">重新加载</button>
                <button type="button" class="stop" @click="stopPreview">停止预览</button>
              </div>
            </div>
          </div>
        </section>

        <section class="drawer-operation-panel drawer-operation-panel-v2">
          <div class="drawer-operation-copy">
            <strong>设备操作</strong>
            <span>检测连接、控制录像、调整配置或进入多画面实时监控。</span>
          </div>
          <div class="drawer-actions drawer-actions-v2">
            <el-button :icon="Connection" :loading="actionCameraId === selectedCamera.id" @click="runAction(selectedCamera, 'probe')">连接检测</el-button>
            <el-button v-if="!isRecording(selectedCamera.id)" type="primary" :icon="VideoPlay" :loading="actionCameraId === selectedCamera.id" @click="runAction(selectedCamera, 'start')">开始录像</el-button>
            <el-button v-else type="danger" plain :icon="VideoPause" :loading="actionCameraId === selectedCamera.id" @click="runAction(selectedCamera, 'stop')">停止录像</el-button>
            <el-button :icon="Edit" @click="openEdit(selectedCamera)">编辑配置</el-button>
            <el-button @click="emit('open-preview')">实时监控</el-button>
          </div>
        </section>

        <div class="detail-columns">
          <section class="detail-section detail-section-v2">
            <div class="detail-heading"><strong>连接信息</strong></div>
            <dl class="detail-grid detail-grid-v2">
              <div><dt>IP 地址</dt><dd>{{ selectedCamera.ip }}</dd></div>
              <div><dt>RTSP 端口</dt><dd>{{ selectedCamera.rtsp_port }}</dd></div>
              <div><dt>用户名</dt><dd>{{ selectedCamera.username || '-' }}</dd></div>
              <div><dt>主码流</dt><dd :title="selectedCamera.rtsp_path">{{ selectedCamera.rtsp_path }}</dd></div>
              <div class="wide"><dt>子码流</dt><dd :title="selectedCamera.sub_rtsp_path || inferSubstreamPath(selectedCamera.rtsp_path) || '未配置'">{{ selectedCamera.sub_rtsp_path || inferSubstreamPath(selectedCamera.rtsp_path) || '未配置' }}</dd></div>
            </dl>
          </section>

          <section class="detail-section detail-section-v2">
            <div class="detail-heading"><strong>视频与录像</strong></div>
            <dl class="detail-grid detail-grid-v2">
              <div><dt>编码</dt><dd>{{ selectedCamera.video_codec?.toUpperCase() || '-' }}</dd></div>
              <div><dt>分辨率</dt><dd>{{ selectedCamera.width && selectedCamera.height ? `${selectedCamera.width}×${selectedCamera.height}` : '-' }}</dd></div>
              <div><dt>帧率</dt><dd>{{ fps(selectedCamera) ? `${fps(selectedCamera)} FPS` : '-' }}</dd></div>
              <div><dt>音频</dt><dd>{{ selectedCamera.audio_codec?.toUpperCase() || '-' }}</dd></div>
              <div><dt>录像策略</dt><dd>{{ schedulePolicyLabel(selectedCamera) }}</dd></div>
              <div><dt>计划状态</dt><dd>{{ scheduleStateLabel(selectedCamera) }}</dd></div>
            </dl>
          </section>
        </div>

        <section class="detail-section detail-section-v2 runtime-section">
          <div class="detail-heading"><strong>运行状态</strong></div>
          <dl class="detail-grid runtime-grid">
            <div><dt>连接状态</dt><dd>{{ healthLabel(selectedCamera) }}</dd></div>
            <div><dt>录像状态</dt><dd>{{ runtimeLabel(selectedCamera) }}</dd></div>
            <div><dt>最近检测</dt><dd>{{ formatTime(selectedCamera.last_probe_at) }}</dd></div>
            <div><dt>最近在线</dt><dd>{{ formatTime(selectedCamera.last_online_at) }}</dd></div>
            <div><dt>时间戳模式</dt><dd>{{ selectedCamera.timestamp_mode }}</dd></div>
            <div><dt>设备类型</dt><dd>{{ formFactorLabel(selectedCamera.form_factor) }}</dd></div>
          </dl>
        </section>

        <section class="drawer-danger-zone">
          <div>
            <strong>删除摄像头</strong>
            <span>删除设备配置；若正在录像，会先停止当前录像任务。</span>
          </div>
          <el-button type="danger" plain :icon="Delete" @click="removeCamera(selectedCamera)">删除</el-button>
        </section>
      </div>
    </el-drawer>

    <el-dialog v-model="dialogVisible" :title="editingId === null ? '添加 RTSP 摄像头' : '编辑摄像头'" width="680px" destroy-on-close>
      <el-form label-width="88px" class="camera-form" @submit.prevent="saveCamera">
        <div class="form-grid">
          <el-form-item label="名称" class="wide"><el-input v-model="form.name" placeholder="例如：门口摄像头" /></el-form-item>
          <el-form-item label="厂商"><el-input v-model="form.manufacturer" placeholder="例如 Hikvision" /></el-form-item>
          <el-form-item label="型号"><el-input v-model="form.model" placeholder="例如 DS-2CD..." /></el-form-item>
          <el-form-item label="外形" class="wide">
            <el-select v-model="form.form_factor" style="width: 100%">
              <el-option v-for="item in formFactorOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="IP 地址"><el-input v-model="form.ip" placeholder="192.168.1.101" /></el-form-item>
          <el-form-item label="RTSP 端口"><el-input-number v-model="form.rtsp_port" :min="1" :max="65535" controls-position="right" /></el-form-item>
          <el-form-item label="用户名"><el-input v-model="form.username" /></el-form-item>
          <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password :placeholder="editingId === null ? '必填' : '留空保持原密码'" /></el-form-item>
          <el-form-item label="主码流" class="wide"><el-input v-model="form.rtsp_path" placeholder="/ch1/main" /></el-form-item>
          <el-form-item label="子码流" class="wide"><el-input v-model="form.sub_rtsp_path" placeholder="可选，例如 /ch1/sub" /></el-form-item>
          <el-form-item label="时间戳">
            <el-select v-model="form.timestamp_mode" style="width: 100%">
              <el-option label="重建时间戳（推荐）" value="reconstruct" />
              <el-option label="使用原始时间戳" value="native" />
              <el-option label="使用系统时间" value="wallclock" />
            </el-select>
          </el-form-item>
          <div class="switch-group">
            <label><span>启用摄像头</span><el-switch v-model="form.enabled" /></label>
            <label><span>自动录像</span><el-switch v-model="form.auto_record" /></label>
          </div>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveCamera">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.camera-page{padding:22px;min-height:100%;color:var(--nvr-text)}
.page-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.page-heading h1{margin:0;font-size:20px;font-weight:680}.page-heading p{margin:6px 0 0;color:var(--nvr-muted);font-size:12px}.heading-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.summary-grid{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.summary-card{appearance:none;color:var(--nvr-text);background:var(--nvr-surface);border:1px solid var(--nvr-border);cursor:pointer}.summary-card span,.summary-card strong{display:inline-block}.summary-card small{display:none}
.toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px}.search-box{width:min(560px,100%)}.camera-sort-select{width:116px;flex:0 0 116px}.result-count{color:var(--nvr-muted);font-size:11px;white-space:nowrap}
.camera-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}.camera-card{min-width:0;display:flex;flex-direction:column;cursor:pointer}.camera-card-topline{display:flex;align-items:flex-start;justify-content:space-between}.camera-icon{display:grid;place-items:center;border:1px solid var(--nvr-border)}.camera-card-id{color:var(--nvr-subtle);font-size:10px}.camera-copy{min-width:0}.camera-name-row{display:flex;align-items:center;gap:6px;min-width:0}.camera-name-row strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.health-badge,.record-badge{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}.health-badge i,.record-badge i{width:6px;height:6px;border-radius:50%;background:var(--nvr-subtle)}.health-badge.online i{background:var(--nvr-green)}.health-badge.offline i{background:var(--nvr-red)}.health-badge.unknown i{background:var(--nvr-yellow)}.record-badge.active i{background:var(--nvr-red)}.camera-identity,.camera-video,.camera-address{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.camera-signals{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.camera-signals span,.camera-signals b{display:block}.camera-card-footer{display:flex;align-items:center;justify-content:space-between;gap:12px}
.empty-state{min-height:330px;display:flex;flex-direction:column;align-items:center;justify-content:center;border:1px dashed var(--nvr-border-strong);border-radius:11px;color:var(--nvr-muted);background:var(--nvr-surface)}.empty-state :deep(svg){width:34px;margin-bottom:12px;color:var(--nvr-subtle)}.empty-state strong{color:var(--nvr-text-soft);font-size:13px}.empty-state span{margin:6px 0 16px;font-size:11px}
.drawer-title{width:100%;display:flex;align-items:center;justify-content:space-between;gap:16px;padding-right:12px}.drawer-title>div:first-child{display:flex;min-width:0;flex-direction:column}.drawer-title strong{font-size:15px}.drawer-title span:not(.health-badge):not(.record-badge){margin-top:3px;color:var(--nvr-muted);font-size:10px}.drawer-title-states{display:flex;align-items:center;gap:6px}.drawer-body{display:flex;flex-direction:column;gap:13px}.drawer-device-nav{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:10px;padding:1px 2px}.drawer-device-nav :deep(.el-button){height:29px;margin:0;padding:0 8px;color:var(--nvr-muted);font-size:10px}.drawer-device-nav :deep(.el-button:first-child){justify-self:start}.drawer-device-nav :deep(.el-button:last-child){justify-self:end;flex-direction:row-reverse}.drawer-device-nav-position{display:flex;align-items:baseline;justify-content:center;gap:6px;color:var(--nvr-muted);white-space:nowrap}.drawer-device-nav-position strong{color:var(--nvr-text-soft);font-size:10px;font-weight:650}.drawer-device-nav-position span{font-size:8px}.device-hero{display:flex;align-items:center;gap:16px}.device-hero-visual{display:grid;place-items:center;border:1px solid var(--nvr-border)}.device-hero-copy{min-width:0;display:flex;flex-direction:column}.preview-panel{position:relative;aspect-ratio:16/9;border:1px solid var(--nvr-border);border-radius:9px;background:#05080c;overflow:hidden}.preview-image{display:block;width:100%;height:100%;object-fit:contain;background:#05080c}.preview-empty{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#617083}.preview-empty :deep(svg){width:34px;margin-bottom:9px}.preview-empty strong{color:#9aa7b7;font-size:12px}.preview-empty span{margin-top:5px;font-size:10px}.preview-overlay{position:absolute;left:0;right:0;bottom:0;display:flex;align-items:flex-end;justify-content:space-between;gap:12px;padding:28px 10px 8px;color:#c4ced8;background:linear-gradient(transparent,rgba(0,0,0,.74));font-size:10px}.preview-overlay-status{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.preview-overlay-status>span{display:inline-flex;align-items:center;gap:5px}.preview-overlay i{width:6px;height:6px;border-radius:50%;background:#6a7787}.preview-overlay i.active{background:var(--nvr-red)}.preview-stream-chip{padding:2px 5px;border:1px solid rgba(255,255,255,.16);border-radius:4px;background:rgba(5,8,12,.44)}.preview-stream-chip.fallback{color:#ffd58a}.preview-overlay button{appearance:none;border:0;color:#c4ced8;background:transparent;cursor:pointer;font-size:10px}.drawer-operation-panel,.detail-section{border:1px solid var(--nvr-border);background:var(--nvr-surface)}.drawer-operation-copy{display:flex;flex-direction:column}.drawer-actions{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.detail-heading{display:flex;align-items:center;justify-content:space-between}.detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px 16px;margin:0}.detail-grid .wide{grid-column:1/-1}.detail-grid dt{margin-bottom:3px;color:var(--nvr-subtle);font-size:9px}.detail-grid dd{margin:0;color:var(--nvr-text-soft);font-size:10px;overflow-wrap:anywhere}.camera-form{padding-top:4px}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 14px}.form-grid .wide{grid-column:1/-1}.form-grid :deep(.el-input-number){width:100%}.switch-group{display:flex;align-items:center;gap:20px;min-height:32px;padding:0 0 18px 88px}.switch-group label{display:flex;align-items:center;gap:9px;color:var(--nvr-muted);font-size:11px}
@media (max-width:760px){.camera-page{padding:14px}.page-heading{flex-direction:column}.heading-actions{width:100%}.camera-list{grid-template-columns:1fr}.toolbar{align-items:stretch;flex-direction:column}.search-box{width:100%}.camera-sort-select{width:100%;flex:none}.detail-grid{grid-template-columns:1fr}.detail-grid .wide{grid-column:auto}.form-grid{grid-template-columns:1fr}.form-grid .wide{grid-column:auto}.switch-group{padding-left:0}.camera-detail-drawer{width:100%!important}.drawer-title{align-items:flex-start}.drawer-title-states{flex-direction:column;align-items:flex-end}}
</style>
